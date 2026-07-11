from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class SearchFilters:
    name: str | None = None
    extension: str | None = None
    min_size: int | None = None
    max_size: int | None = None
    disk_id: int | None = None
    scan_id: int | None = None
    modified_after: str | None = None
    modified_before: str | None = None
    limit: int | None = 200


def _build_where(filters: SearchFilters) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    if filters.name:
        clauses.append("filename LIKE ?")
        params.append(f"%{filters.name}%")
    if filters.extension:
        ext = filters.extension if filters.extension.startswith(".") else f".{filters.extension}"
        clauses.append("extension = ?")
        params.append(ext.lower())
    if filters.min_size is not None:
        clauses.append("size_bytes >= ?")
        params.append(filters.min_size)
    if filters.max_size is not None:
        clauses.append("size_bytes <= ?")
        params.append(filters.max_size)
    if filters.disk_id is not None:
        clauses.append("disk_id = ?")
        params.append(filters.disk_id)
    if filters.scan_id is not None:
        clauses.append("scan_id = ?")
        params.append(filters.scan_id)
    if filters.modified_after:
        clauses.append("modified_date >= ?")
        params.append(filters.modified_after)
    if filters.modified_before:
        clauses.append("modified_date <= ?")
        params.append(filters.modified_before)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def search_files(conn: sqlite3.Connection, filters: SearchFilters) -> list[sqlite3.Row]:
    where, params = _build_where(filters)
    sql = f"""
        SELECT id, disk_id, path, filename, extension, size_bytes, modified_date, hash
        FROM files
        {where}
        ORDER BY modified_date DESC
    """
    if filters.limit is not None:
        sql += " LIMIT ?"
        params = params + [filters.limit]
    return conn.execute(sql, params).fetchall()


def export_rows(conn: sqlite3.Connection, filters: SearchFilters | None = None) -> list[sqlite3.Row]:
    """Full-column rows (disk label, both dates, mime type) for report export.

    Unlike search_files, defaults to no row limit since an export is meant to
    capture everything that matched.
    """
    filters = filters or SearchFilters(limit=None)
    where, params = _build_where(filters)
    sql = f"""
        SELECT f.disk_id, d.label AS disk_label, f.path, f.filename, f.extension,
               f.size_bytes, f.created_date, f.modified_date, f.hash, f.mime_type
        FROM files f
        JOIN disks d ON d.disk_id = f.disk_id
        {where}
        ORDER BY f.path
    """
    if filters.limit is not None:
        sql += " LIMIT ?"
        params = params + [filters.limit]
    return conn.execute(sql, params).fetchall()


def find_duplicates(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Group files by content hash to surface duplicates across all scanned disks."""
    sql = """
        SELECT hash, COUNT(*) AS copies, SUM(size_bytes) AS total_bytes
        FROM files
        WHERE hash IS NOT NULL
        GROUP BY hash
        HAVING COUNT(*) > 1
        ORDER BY total_bytes DESC
        LIMIT ?
    """
    return conn.execute(sql, (limit,)).fetchall()


def files_for_hash(conn: sqlite3.Connection, file_hash: str) -> list[sqlite3.Row]:
    sql = """
        SELECT id, disk_id, path, filename, size_bytes, modified_date
        FROM files
        WHERE hash = ?
        ORDER BY path
    """
    return conn.execute(sql, (file_hash,)).fetchall()


def catalog_stats(conn: sqlite3.Connection) -> dict:
    totals = conn.execute(
        "SELECT COUNT(*) AS file_count, COALESCE(SUM(size_bytes), 0) AS total_bytes FROM files"
    ).fetchone()
    per_disk = conn.execute(
        """
        SELECT d.disk_id, d.label, d.volume_serial,
               COUNT(f.id) AS file_count, COALESCE(SUM(f.size_bytes), 0) AS total_bytes
        FROM disks d
        LEFT JOIN files f ON f.disk_id = d.disk_id
        GROUP BY d.disk_id
        ORDER BY d.disk_id
        """
    ).fetchall()
    return {
        "file_count": totals["file_count"],
        "total_bytes": totals["total_bytes"],
        "disks": per_disk,
    }
