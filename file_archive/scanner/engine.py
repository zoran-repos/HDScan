from __future__ import annotations

import logging
import mimetypes
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from file_archive.scanner.hasher import hash_file
from file_archive.scanner.volume import get_volume_info

HASH_MODES = ("full", "sampled", "none")

logger = logging.getLogger("file_archive.scanner")

BATCH_SIZE = 1000

_UPSERT_FILE_SQL = """
INSERT INTO files (
    disk_id, scan_id, path, filename, extension, size_bytes,
    created_date, modified_date, hash, hash_algo, mime_type, last_seen
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(disk_id, path) DO UPDATE SET
    scan_id=excluded.scan_id,
    filename=excluded.filename,
    extension=excluded.extension,
    size_bytes=excluded.size_bytes,
    created_date=excluded.created_date,
    modified_date=excluded.modified_date,
    hash=excluded.hash,
    hash_algo=excluded.hash_algo,
    mime_type=excluded.mime_type,
    last_seen=excluded.last_seen
"""

_INSERT_ERROR_SQL = """
INSERT INTO scan_errors (scan_id, path, error_message, occurred_at)
VALUES (?, ?, ?, ?)
"""


@dataclass
class ScanResult:
    scan_id: int
    disk_id: int
    files_scanned: int
    files_failed: int


@dataclass
class ScanProgress:
    files_scanned: int
    files_failed: int
    current_path: str


ProgressCallback = Callable[[ScanProgress], None]

_PROGRESS_INTERVAL_SECONDS = 0.2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_or_create_disk(conn: sqlite3.Connection, root_path: Path) -> int:
    info = get_volume_info(root_path)
    now = _now()
    row = conn.execute(
        "SELECT disk_id FROM disks WHERE volume_serial = ?", (info.serial,)
    ).fetchone()
    if row is not None:
        disk_id = row["disk_id"]
        # label is intentionally NOT touched here - the user may have
        # renamed it via the web UI, and re-scanning shouldn't overwrite
        # that with the raw OS volume label again.
        conn.execute(
            "UPDATE disks SET filesystem=?, total_bytes=?, last_scanned=? "
            "WHERE disk_id=?",
            (info.filesystem, info.total_bytes, now, disk_id),
        )
        return disk_id

    cur = conn.execute(
        "INSERT INTO disks (volume_serial, label, filesystem, total_bytes, first_seen, last_scanned) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (info.serial, info.label, info.filesystem, info.total_bytes, now, now),
    )
    return cur.lastrowid


def _mark_stale_scans_interrupted(conn: sqlite3.Connection, disk_id: int) -> None:
    """A scan row left in 'running' status with no finished_at means the
    process died before _finish_scan ran (killed, crashed, machine slept).
    Mark those as 'interrupted' so the scans table doesn't lie forever."""
    conn.execute(
        "UPDATE scans SET status='interrupted', finished_at=? "
        "WHERE disk_id=? AND status='running'",
        (_now(), disk_id),
    )


def _start_scan(conn: sqlite3.Connection, disk_id: int, root_path: Path) -> int:
    cur = conn.execute(
        "INSERT INTO scans (disk_id, root_path, started_at, status) VALUES (?, ?, ?, 'running')",
        (disk_id, str(root_path), _now()),
    )
    return cur.lastrowid


def _load_existing_files(conn: sqlite3.Connection, disk_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT path, size_bytes, modified_date, hash, hash_algo FROM files WHERE disk_id = ?",
        (disk_id,),
    ).fetchall()
    return {row["path"]: row for row in rows}


def _finish_scan(
    conn: sqlite3.Connection,
    scan_id: int,
    files_scanned: int,
    files_failed: int,
    status: str = "completed",
) -> None:
    conn.execute(
        "UPDATE scans SET finished_at=?, status=?, files_scanned=?, files_failed=? "
        "WHERE scan_id=?",
        (_now(), status, files_scanned, files_failed, scan_id),
    )


def scan_directory(
    conn: sqlite3.Connection,
    root_path: Path,
    hash_mode: str = "sampled",
    progress_callback: ProgressCallback | None = None,
) -> ScanResult:
    """Walk root_path, hashing and cataloging every file found.

    Rows are buffered and flushed in batches of BATCH_SIZE inside explicit
    transactions so a 1M+ file scan never does a per-row commit. Per-file and
    per-directory errors are captured into scan_errors instead of aborting
    the whole scan.

    hash_mode controls how file content hashes are computed - see
    file_archive.scanner.hasher.hash_file for the "full" / "sampled" / "none"
    trade-offs. "sampled" (the default) only fully hashes files above
    hasher.LARGE_FILE_THRESHOLD by reading a head/tail sample instead, which
    is what keeps large media collections on slow drives from taking days.

    Files already cataloged for this disk whose size and modified_date
    haven't changed since the last scan reuse their stored hash instead of
    being re-hashed - so re-running a scan that got interrupted (power loss,
    a sleeping external drive, a closed terminal) only pays the hashing cost
    for files it hasn't already seen, not the whole disk again.

    If given, progress_callback is invoked at most every
    _PROGRESS_INTERVAL_SECONDS (not per-file) so callers can render live
    feedback without the reporting itself slowing the scan down.
    """
    if hash_mode not in HASH_MODES:
        raise ValueError(f"hash_mode must be one of {HASH_MODES}, got {hash_mode!r}")

    root_path = Path(root_path).resolve()
    if not root_path.exists():
        raise FileNotFoundError(root_path)

    disk_id = _get_or_create_disk(conn, root_path)
    _mark_stale_scans_interrupted(conn, disk_id)
    existing_files = _load_existing_files(conn, disk_id)
    scan_id = _start_scan(conn, disk_id, root_path)

    file_rows: list[tuple] = []
    error_rows: list[tuple] = []
    counters = {"scanned": 0, "failed": 0}
    last_report = {"time": 0.0}

    def report(current_path: str) -> None:
        if progress_callback is None:
            return
        now = time.monotonic()
        if now - last_report["time"] < _PROGRESS_INTERVAL_SECONDS:
            return
        last_report["time"] = now
        progress_callback(
            ScanProgress(
                files_scanned=counters["scanned"],
                files_failed=counters["failed"],
                current_path=current_path,
            )
        )

    def flush() -> None:
        if not file_rows and not error_rows:
            return
        conn.execute("BEGIN IMMEDIATE;")
        try:
            if file_rows:
                conn.executemany(_UPSERT_FILE_SQL, file_rows)
            if error_rows:
                conn.executemany(_INSERT_ERROR_SQL, error_rows)
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        file_rows.clear()
        error_rows.clear()

    def on_walk_error(exc: OSError) -> None:
        path = getattr(exc, "filename", "") or ""
        logger.warning("Directory walk error at %s: %s", path, exc)
        error_rows.append((scan_id, path, str(exc), _now()))
        counters["failed"] += 1

    try:
        for dirpath, _dirnames, filenames in os.walk(root_path, onerror=on_walk_error):
            for name in filenames:
                full_path = Path(dirpath) / name
                try:
                    stat = full_path.stat()
                    modified_date = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                    path_str = str(full_path)

                    prior = existing_files.get(path_str)
                    if (
                        prior is not None
                        and prior["size_bytes"] == stat.st_size
                        and prior["modified_date"] == modified_date
                    ):
                        file_hash, hash_algo = prior["hash"], prior["hash_algo"]
                    else:
                        file_hash, hash_algo = hash_file(full_path, stat.st_size, mode=hash_mode)

                    mime_type, _enc = mimetypes.guess_type(name)
                    file_rows.append(
                        (
                            disk_id,
                            scan_id,
                            path_str,
                            name,
                            full_path.suffix.lower(),
                            stat.st_size,
                            datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                            modified_date,
                            file_hash,
                            hash_algo,
                            mime_type,
                            _now(),
                        )
                    )
                    counters["scanned"] += 1
                except OSError as exc:
                    logger.warning("Failed to catalog %s: %s", full_path, exc)
                    error_rows.append((scan_id, str(full_path), str(exc), _now()))
                    counters["failed"] += 1

                if len(file_rows) >= BATCH_SIZE or len(error_rows) >= BATCH_SIZE:
                    flush()

                report(str(full_path))

        flush()
        if progress_callback is not None:
            progress_callback(
                ScanProgress(
                    files_scanned=counters["scanned"],
                    files_failed=counters["failed"],
                    current_path="",
                )
            )
        _finish_scan(conn, scan_id, counters["scanned"], counters["failed"])
    except KeyboardInterrupt:
        # Ctrl+C: save whatever was buffered since the last batch commit
        # (rather than discarding up to BATCH_SIZE-1 already-hashed rows for
        # no reason) and mark the scan as cleanly interrupted, not failed.
        flush()
        _finish_scan(conn, scan_id, counters["scanned"], counters["failed"], status="interrupted")
        raise
    except Exception:
        flush()
        _finish_scan(conn, scan_id, counters["scanned"], counters["failed"], status="failed")
        raise

    return ScanResult(
        scan_id=scan_id,
        disk_id=disk_id,
        files_scanned=counters["scanned"],
        files_failed=counters["failed"],
    )
