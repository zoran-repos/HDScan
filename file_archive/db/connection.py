from __future__ import annotations

import sqlite3
from pathlib import Path

from file_archive.db.schema import migrate

_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",
    "PRAGMA temp_store=MEMORY;",
    "PRAGMA cache_size=10000;",
    "PRAGMA foreign_keys=ON;",
    # A scan (writer) and the web UI (reader, occasionally a writer for disk
    # rename/description) can be open at the same time. WAL lets readers
    # proceed without blocking, but two writers can still momentarily
    # collide during a scan's batch commit - without this, that split
    # second raises "database is locked" instead of just waiting it out.
    "PRAGMA busy_timeout=5000;",
)


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the performance/safety PRAGMAs applied and the
    schema migrated to the latest version."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    migrate(conn)
    return conn
