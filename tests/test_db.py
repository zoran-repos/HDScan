import sqlite3
from pathlib import Path

from file_archive.db.connection import connect
from file_archive.db.schema import SCHEMA_VERSION, _DDL_V1


def test_connect_creates_schema(tmp_path: Path):
    db_path = tmp_path / "archive.db"
    conn = connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"disks", "scans", "files", "scan_errors"} <= tables

    journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert journal_mode.lower() == "wal"

    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "idx_files_hash",
        "idx_files_filename",
        "idx_files_disk_id",
        "idx_files_modified_date",
    } <= indexes

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(disks)")}
    assert "description" in columns

    conn.close()


def test_connect_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "archive.db"
    connect(db_path).close()
    conn2 = connect(db_path)  # re-opening/migrating an existing db must not raise
    version = conn2.execute("PRAGMA user_version;").fetchone()[0]
    assert version == SCHEMA_VERSION
    conn2.close()


def test_migration_from_v1_adds_description_without_data_loss(tmp_path: Path):
    db_path = tmp_path / "archive.db"
    # Simulate a pre-existing database created before the description column existed.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL_V1)
    conn.execute(
        "INSERT INTO disks (volume_serial, label, first_seen) VALUES (?, ?, ?)",
        ("ABCD1234", "Old Disk", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute("PRAGMA user_version=1;")
    conn.commit()
    conn.close()

    migrated = connect(db_path)
    version = migrated.execute("PRAGMA user_version;").fetchone()[0]
    assert version == SCHEMA_VERSION

    row = migrated.execute("SELECT label, description FROM disks WHERE volume_serial='ABCD1234'").fetchone()
    assert row["label"] == "Old Disk"  # pre-existing data survives
    assert row["description"] is None  # new column defaults to NULL

    migrated.close()
