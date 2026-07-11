"""Crash-safe backups of the catalog database.

Uses sqlite3's built-in online backup API (Connection.backup) rather than a
raw file copy: a plain shutil.copy2 of a WAL-mode database can capture the
main DB file mid-checkpoint and miss data still sitting in the -wal file,
whereas the backup API produces a consistent snapshot regardless of WAL
state.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("file_archive.backup")

_BACKUP_GLOB = "archive_*.db"
DEFAULT_KEEP = 30


def _timestamped_name() -> str:
    return f"archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"


def backup_now(source_conn: sqlite3.Connection, backups_dir: Path, keep: int = DEFAULT_KEEP) -> Path:
    """Snapshot the live database into backups_dir and enforce retention."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backups_dir / _timestamped_name()

    dest_conn = sqlite3.connect(str(backup_file))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()

    logger.info("Database backed up to %s", backup_file)
    cleanup_old_backups(backups_dir, keep=keep)
    return backup_file


def cleanup_old_backups(backups_dir: Path, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Keep only the newest `keep` backup files; delete the rest."""
    backups = sorted(backups_dir.glob(_BACKUP_GLOB))
    removed: list[Path] = []
    excess = len(backups) - keep
    if excess > 0:
        for old_backup in backups[:excess]:
            old_backup.unlink()
            removed.append(old_backup)
            logger.info("Removed old backup %s", old_backup)
    return removed


def has_backup_today(backups_dir: Path) -> bool:
    today = datetime.now().strftime("%Y%m%d")
    return any(backups_dir.glob(f"archive_{today}_*.db"))


def backup_if_needed(
    source_conn: sqlite3.Connection, backups_dir: Path, keep: int = DEFAULT_KEEP
) -> Path | None:
    """Back up once per day or when explicitly forced via backup_now."""
    if has_backup_today(backups_dir):
        return None
    return backup_now(source_conn, backups_dir, keep=keep)
