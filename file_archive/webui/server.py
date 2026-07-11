"""Local-only web UI for browsing the catalog like a file manager.

Deliberately built on the stdlib http.server rather than adding a web
framework dependency - the API surface is tiny (three JSON endpoints plus
static files) and always binds to 127.0.0.1, never the network.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from file_archive.categorize import categorize
from file_archive.db.connection import connect
from file_archive.humanize import human_size
from file_archive.search.query import SearchFilters, search_files
from file_archive.webui.reveal import reveal_in_explorer
from file_archive.webui.tree import browse, list_disks, update_disk

STATIC_DIR = (Path(__file__).parent / "static").resolve()

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = min(int(handler.headers.get("Content-Length", 0) or 0), 65536)
    raw_body = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw_body or b"{}")


def _search_results(conn, disk_id: int | None, query: str) -> list[dict]:
    filters = SearchFilters(name=query or None, disk_id=disk_id, limit=200)
    rows = search_files(conn, filters)
    return [
        {
            "name": r["filename"],
            "path": r["path"],
            "extension": r["extension"] or "",
            "category": categorize(r["extension"]),
            "size_bytes": r["size_bytes"],
            "size_human": human_size(r["size_bytes"]),
            "modified_date": r["modified_date"],
        }
        for r in rows
    ]


def make_handler(db_path: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            pass  # keep the terminal quiet; unhandled exceptions still surface

        def _serve_static(self, url_path: str) -> None:
            rel = url_path.lstrip("/") or "index.html"
            candidate = (STATIC_DIR / rel).resolve()
            try:
                candidate.relative_to(STATIC_DIR)
            except ValueError:
                self.send_error(403, "Forbidden")
                return
            if not candidate.exists() or candidate.is_dir():
                self.send_error(404, "Not found")
                return
            body = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _CONTENT_TYPES.get(candidate.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)

            if parsed.path == "/api/disks":
                conn = connect(db_path)
                try:
                    _write_json(self, 200, list_disks(conn))
                finally:
                    conn.close()
                return

            if parsed.path == "/api/browse":
                disk_id_raw = query.get("disk_id", [None])[0]
                if disk_id_raw is None:
                    _write_json(self, 400, {"error": "disk_id is required"})
                    return
                folder = query.get("folder", [""])[0] or None
                conn = connect(db_path)
                try:
                    _write_json(self, 200, browse(conn, int(disk_id_raw), folder))
                finally:
                    conn.close()
                return

            if parsed.path == "/api/search":
                disk_id_raw = query.get("disk_id", [None])[0]
                q = query.get("q", [""])[0]
                conn = connect(db_path)
                try:
                    disk_id = int(disk_id_raw) if disk_id_raw else None
                    _write_json(self, 200, _search_results(conn, disk_id, q))
                finally:
                    conn.close()
                return

            self._serve_static(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)

            if parsed.path == "/api/disks/update":
                query = parse_qs(parsed.query)
                disk_id_raw = query.get("disk_id", [None])[0]
                if disk_id_raw is None:
                    _write_json(self, 400, {"error": "disk_id is required"})
                    return

                try:
                    payload = _read_json_body(self)
                except json.JSONDecodeError:
                    _write_json(self, 400, {"error": "invalid JSON body"})
                    return

                conn = connect(db_path)
                try:
                    update_disk(
                        conn,
                        int(disk_id_raw),
                        label=payload.get("label"),
                        description=payload.get("description"),
                    )
                    updated = next(
                        (d for d in list_disks(conn) if d["disk_id"] == int(disk_id_raw)), None
                    )
                    if updated is None:
                        _write_json(self, 404, {"error": "disk not found"})
                    else:
                        _write_json(self, 200, updated)
                finally:
                    conn.close()
                return

            if parsed.path == "/api/reveal":
                try:
                    payload = _read_json_body(self)
                except json.JSONDecodeError:
                    _write_json(self, 400, {"error": "invalid JSON body"})
                    return

                path = payload.get("path")
                if not path:
                    _write_json(self, 400, {"error": "path is required"})
                    return

                conn = connect(db_path)
                try:
                    # Only reveal paths that are actually in our own catalog -
                    # this endpoint shells out to explorer.exe, so it must
                    # never act on an arbitrary path a request happens to send.
                    known = conn.execute(
                        "SELECT 1 FROM files WHERE path = ? LIMIT 1", (path,)
                    ).fetchone()
                finally:
                    conn.close()

                if known is None:
                    _write_json(self, 404, {"error": "path not found in catalog"})
                    return

                if not Path(path).exists():
                    _write_json(self, 409, {"error": "file not currently accessible (disk unplugged?)"})
                    return

                reveal_in_explorer(path)
                _write_json(self, 200, {"ok": True})
                return

            self.send_error(404, "Not found")

    return Handler


def run_server(db_path: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    handler_cls = make_handler(db_path)
    httpd = ThreadingHTTPServer((host, port), handler_cls)
    url = f"http://{host}:{port}/"
    print(f"File Archive Browser running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
