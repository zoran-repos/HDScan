from pathlib import Path

from file_archive.backup.manager import (
    backup_if_needed,
    backup_now,
    cleanup_old_backups,
    has_backup_today,
)
from file_archive.db.connection import connect


def _new_conn(tmp_path: Path):
    db_path = tmp_path / "db" / "archive.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return connect(db_path)


def test_backup_now_creates_file(tmp_path: Path):
    conn = _new_conn(tmp_path)
    backups_dir = tmp_path / "backups"

    backup_path = backup_now(conn, backups_dir)

    assert backup_path.exists()
    assert backup_path.parent == backups_dir
    conn.close()


def test_backup_if_needed_only_once_per_day(tmp_path: Path):
    conn = _new_conn(tmp_path)
    backups_dir = tmp_path / "backups"

    first = backup_if_needed(conn, backups_dir)
    second = backup_if_needed(conn, backups_dir)

    assert first is not None
    assert second is None
    assert has_backup_today(backups_dir)
    conn.close()


def test_cleanup_keeps_only_newest_n(tmp_path: Path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()

    names = []
    for i in range(35):
        name = f"archive_20260101_{i:06d}.db"
        (backups_dir / name).write_bytes(b"fake")
        names.append(name)

    removed = cleanup_old_backups(backups_dir, keep=30)

    remaining = sorted(p.name for p in backups_dir.glob("archive_*.db"))
    assert len(remaining) == 30
    assert len(removed) == 5
    assert remaining == sorted(names)[5:]
