from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

_DDL_V1 = """
CREATE TABLE IF NOT EXISTS disks (
    disk_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_serial   TEXT UNIQUE NOT NULL,
    label           TEXT,
    filesystem      TEXT,
    total_bytes     INTEGER,
    first_seen      TEXT NOT NULL,
    last_scanned    TEXT
);

CREATE TABLE IF NOT EXISTS scans (
    scan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    disk_id         INTEGER NOT NULL REFERENCES disks(disk_id),
    root_path       TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    files_scanned   INTEGER NOT NULL DEFAULT 0,
    files_failed    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    disk_id         INTEGER NOT NULL REFERENCES disks(disk_id),
    scan_id         INTEGER NOT NULL REFERENCES scans(scan_id),
    path            TEXT NOT NULL,
    filename        TEXT NOT NULL,
    extension       TEXT,
    size_bytes      INTEGER NOT NULL,
    created_date    TEXT,
    modified_date   TEXT,
    hash            TEXT,
    hash_algo       TEXT,
    mime_type       TEXT,
    thumbnail_path  TEXT,
    last_seen       TEXT NOT NULL,
    UNIQUE(disk_id, path)
);

CREATE TABLE IF NOT EXISTS scan_errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL REFERENCES scans(scan_id),
    path            TEXT,
    error_message   TEXT,
    occurred_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);
CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);
CREATE INDEX IF NOT EXISTS idx_files_disk_id ON files(disk_id);
CREATE INDEX IF NOT EXISTS idx_files_modified_date ON files(modified_date);
"""

_DDL_V2 = """
ALTER TABLE disks ADD COLUMN description TEXT;
"""

_MIGRATIONS: list[tuple[int, str]] = [
    (1, _DDL_V1),
    (2, _DDL_V2),
]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply any migrations newer than the database's current user_version,
    in order, so existing databases pick up only the delta rather than
    re-running everything from scratch."""
    current_version = conn.execute("PRAGMA user_version;").fetchone()[0]
    for version, ddl in _MIGRATIONS:
        if current_version >= version:
            continue
        conn.executescript(ddl)
        conn.execute(f"PRAGMA user_version={version};")
        current_version = version
