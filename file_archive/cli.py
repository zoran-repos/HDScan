from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from file_archive.app_paths import get_app_paths
from file_archive.backup.manager import backup_if_needed, backup_now
from file_archive.db.connection import connect
from file_archive.export.excel import export_catalog_to_excel
from file_archive.humanize import human_size
from file_archive.logging_config import configure_logging
from file_archive.scanner.engine import ScanProgress, scan_directory
from file_archive.search.query import SearchFilters, catalog_stats, find_duplicates, search_files
from file_archive.webui.server import run_server


def _print_progress(progress: ScanProgress, start_time: float) -> None:
    elapsed = max(time.monotonic() - start_time, 0.001)
    rate = progress.files_scanned / elapsed
    width = shutil.get_terminal_size(fallback=(100, 20)).columns
    line = f"  {progress.files_scanned} scanned, {progress.files_failed} errors, {rate:.0f} files/s  {progress.current_path}"
    sys.stdout.write("\r" + line[: width - 1].ljust(width - 1))
    sys.stdout.flush()


def _safe_filename_part(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", text).strip() or "disk"


def cmd_scan(args: argparse.Namespace) -> int:
    paths = get_app_paths()
    logger = configure_logging(paths.logs_dir)
    conn = connect(paths.db_path)

    root = Path(args.path)
    if not root.exists():
        print(f"Path does not exist: {root}", file=sys.stderr)
        return 1

    print(f"Scanning {root} ...")
    start_time = time.monotonic()
    try:
        result = scan_directory(
            conn,
            root,
            hash_mode=args.hash_mode,
            progress_callback=lambda p: _print_progress(p, start_time),
        )
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * (shutil.get_terminal_size(fallback=(100, 20)).columns - 1) + "\r")
        print(
            "\nScan interrupted (Ctrl+C). Everything scanned so far is saved - "
            "run scan again on the same path to pick up where this left off "
            "(unchanged files won't be re-hashed)."
        )
        conn.close()
        return 130

    sys.stdout.write("\r" + " " * (shutil.get_terminal_size(fallback=(100, 20)).columns - 1) + "\r")
    print(
        f"Scan complete: {result.files_scanned} files cataloged, "
        f"{result.files_failed} errors (scan_id={result.scan_id}, disk_id={result.disk_id})"
    )

    backup_path = backup_if_needed(conn, paths.backups_dir)
    if backup_path:
        print(f"Backup created: {backup_path}")

    if not args.no_excel:
        if args.excel:
            excel_output = Path(args.excel)
        else:
            disk_row = conn.execute(
                "SELECT label FROM disks WHERE disk_id = ?", (result.disk_id,)
            ).fetchone()
            label = _safe_filename_part(disk_row["label"] if disk_row and disk_row["label"] else "disk")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            excel_output = paths.reports_dir / f"{label}_scan{result.scan_id}_{timestamp}.xlsx"

        excel_path = export_catalog_to_excel(
            conn, excel_output, SearchFilters(scan_id=result.scan_id, limit=None)
        )
        print(f"Excel report written: {excel_path}")

    logger.info(
        "Scan finished: scan_id=%s files_scanned=%s files_failed=%s",
        result.scan_id, result.files_scanned, result.files_failed,
    )
    conn.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    paths = get_app_paths()
    conn = connect(paths.db_path)

    if args.dupes:
        rows = find_duplicates(conn, limit=args.limit)
        if not rows:
            print("No duplicates found.")
        for row in rows:
            print(f"{row['hash'][:16]}...  copies={row['copies']}  total={human_size(row['total_bytes'])}")
        conn.close()
        return 0

    filters = SearchFilters(
        name=args.query,
        extension=args.ext,
        min_size=args.min_size,
        max_size=args.max_size,
        disk_id=args.disk,
        limit=args.limit,
    )
    rows = search_files(conn, filters)
    if not rows:
        print("No matches.")
    for row in rows:
        print(f"[{row['disk_id']}] {row['path']}  ({human_size(row['size_bytes'])}, modified {row['modified_date']})")
    print(f"\n{len(rows)} result(s)")
    conn.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    paths = get_app_paths()
    conn = connect(paths.db_path)
    stats = catalog_stats(conn)
    print(f"Total files: {stats['file_count']}")
    print(f"Total size:  {human_size(stats['total_bytes'])}")
    print("\nPer disk:")
    for disk in stats["disks"]:
        label = disk["label"] or "(unlabeled)"
        print(
            f"  disk_id={disk['disk_id']} [{disk['volume_serial']}] {label}: "
            f"{disk['file_count']} files, {human_size(disk['total_bytes'])}"
        )
    conn.close()
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    paths = get_app_paths()
    conn = connect(paths.db_path)
    backup_path = backup_now(conn, paths.backups_dir)
    print(f"Backup created: {backup_path}")
    conn.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    paths = get_app_paths()
    conn = connect(paths.db_path)

    filters = SearchFilters(
        name=args.query,
        extension=args.ext,
        min_size=args.min_size,
        max_size=args.max_size,
        disk_id=args.disk,
        limit=None,
    )
    excel_path = export_catalog_to_excel(conn, Path(args.output), filters)
    print(f"Excel report written: {excel_path}")
    conn.close()
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    paths = get_app_paths()
    run_server(paths.db_path, port=args.port, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="file_archive", description="File Archive Catalog & Disk Intelligence System")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_p = subparsers.add_parser("scan", help="Scan a directory/drive into the catalog")
    scan_p.add_argument("path", help="Directory or drive root to scan")
    scan_p.add_argument(
        "--hash-mode",
        choices=("full", "sampled", "none"),
        default="sampled",
        help=(
            "full: read every byte (slowest, exact dedupe). "
            "sampled (default): full hash under 50MB, head+tail+size sample above it "
            "(fast on large media collections, tiny false-match risk). "
            "none: skip hashing entirely (fastest, no dedupe)"
        ),
    )
    scan_p.add_argument("--excel", default=None, metavar="PATH", help="Write the Excel report to this exact path instead of the default reports folder")
    scan_p.add_argument("--no-excel", action="store_true", help="Skip generating an Excel report for this scan")
    scan_p.set_defaults(func=cmd_scan)

    search_p = subparsers.add_parser("search", help="Search the catalog")
    search_p.add_argument("query", nargs="?", default=None, help="Filename substring to search for")
    search_p.add_argument("--ext", default=None, help="Filter by extension, e.g. .jpg")
    search_p.add_argument("--min-size", type=int, default=None, help="Minimum size in bytes")
    search_p.add_argument("--max-size", type=int, default=None, help="Maximum size in bytes")
    search_p.add_argument("--disk", type=int, default=None, help="Filter by disk_id")
    search_p.add_argument("--dupes", action="store_true", help="List duplicate files by content hash")
    search_p.add_argument("--limit", type=int, default=200, help="Max results")
    search_p.set_defaults(func=cmd_search)

    stats_p = subparsers.add_parser("stats", help="Show catalog statistics")
    stats_p.set_defaults(func=cmd_stats)

    backup_p = subparsers.add_parser("backup", help="Force an immediate database backup")
    backup_p.set_defaults(func=cmd_backup)

    export_p = subparsers.add_parser("export", help="Export the catalog (optionally filtered) to an Excel file")
    export_p.add_argument("output", help="Destination .xlsx path")
    export_p.add_argument("query", nargs="?", default=None, help="Filename substring to filter by")
    export_p.add_argument("--ext", default=None, help="Filter by extension, e.g. .jpg")
    export_p.add_argument("--min-size", type=int, default=None, help="Minimum size in bytes")
    export_p.add_argument("--max-size", type=int, default=None, help="Maximum size in bytes")
    export_p.add_argument("--disk", type=int, default=None, help="Filter by disk_id")
    export_p.set_defaults(func=cmd_export)

    browse_p = subparsers.add_parser("browse", help="Launch the local web UI to browse the catalog like a file manager")
    browse_p.add_argument("--port", type=int, default=8765, help="Local port to listen on")
    browse_p.add_argument("--no-browser", action="store_true", help="Don't automatically open the default web browser")
    browse_p.set_defaults(func=cmd_browse)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
