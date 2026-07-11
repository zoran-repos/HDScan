"""Derive a browsable folder hierarchy from the flat files.path column.

There is no folders table - a file's containing folders only exist as
prefixes of its stored path. Given a disk and a folder prefix, this groups
that disk's files by "next path segment after the prefix" to produce the
immediate subfolders and direct files a file-manager UI would show.
"""

from __future__ import annotations

import sqlite3

from file_archive.categorize import categorize
from file_archive.humanize import human_size

SEP = "\\"


def _split(path: str) -> list[str]:
    return [p for p in path.split(SEP) if p]


def _join(parts: list[str]) -> str:
    return SEP.join(parts)


def list_disks(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT d.disk_id, d.label, d.description, d.volume_serial,
               COUNT(f.id) AS file_count, COALESCE(SUM(f.size_bytes), 0) AS total_bytes
        FROM disks d
        LEFT JOIN files f ON f.disk_id = d.disk_id
        GROUP BY d.disk_id
        ORDER BY d.disk_id
        """
    ).fetchall()
    return [
        {
            "disk_id": r["disk_id"],
            "label": r["label"] or "(unlabeled)",
            "description": r["description"] or "",
            "volume_serial": r["volume_serial"],
            "file_count": r["file_count"],
            "total_bytes": r["total_bytes"],
            "size_human": human_size(r["total_bytes"]),
        }
        for r in rows
    ]


def update_disk(
    conn: sqlite3.Connection,
    disk_id: int,
    label: str | None = None,
    description: str | None = None,
) -> None:
    """Update user-editable disk metadata. Only fields explicitly passed
    (not None) are changed; pass an empty string to clear a field."""
    fields: list[str] = []
    params: list[object] = []
    if label is not None:
        fields.append("label = ?")
        params.append(label.strip())
    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())
    if not fields:
        return
    params.append(disk_id)
    conn.execute(f"UPDATE disks SET {', '.join(fields)} WHERE disk_id = ?", params)


def _browse_once(conn: sqlite3.Connection, disk_id: int, folder: str | None) -> dict:
    prefix_parts = _split(folder) if folder else []
    depth = len(prefix_parts)
    prefix = _join(prefix_parts) + SEP if prefix_parts else ""

    # Escape LIKE wildcards in the prefix with '!' (not '\', since '\' is the
    # path separator and would otherwise be reinterpreted as an escape char).
    escaped_prefix = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    rows = conn.execute(
        "SELECT path, extension, size_bytes, modified_date, hash "
        "FROM files WHERE disk_id = ? AND path LIKE ? ESCAPE '!'",
        (disk_id, escaped_prefix + "%"),
    ).fetchall()

    folder_agg: dict[str, dict] = {}
    files: list[dict] = []

    for row in rows:
        parts = _split(row["path"])
        if len(parts) <= depth:
            continue
        remainder = parts[depth:]
        if len(remainder) == 1:
            files.append(
                {
                    "name": remainder[0],
                    "path": row["path"],
                    "extension": row["extension"] or "",
                    "category": categorize(row["extension"]),
                    "size_bytes": row["size_bytes"],
                    "size_human": human_size(row["size_bytes"]),
                    "modified_date": row["modified_date"],
                    "hash": row["hash"],
                }
            )
        else:
            name = remainder[0]
            agg = folder_agg.setdefault(name, {"file_count": 0, "total_bytes": 0})
            agg["file_count"] += 1
            agg["total_bytes"] += row["size_bytes"] or 0

    folders = [
        {
            "name": name,
            "path": _join(prefix_parts + [name]),
            "file_count": agg["file_count"],
            "total_bytes": agg["total_bytes"],
            "size_human": human_size(agg["total_bytes"]),
        }
        for name, agg in sorted(folder_agg.items(), key=lambda kv: kv[0].lower())
    ]
    files.sort(key=lambda f: f["name"].lower())

    parent_path = _join(prefix_parts[:-1]) if len(prefix_parts) > 1 else None

    return {
        "disk_id": disk_id,
        "current_path": _join(prefix_parts),
        "parent_path": parent_path,
        "folders": folders,
        "files": files,
    }


def browse(conn: sqlite3.Connection, disk_id: int, folder: str | None = None) -> dict:
    """List the immediate subfolders and files under folder (None = disk root).

    A root browse (folder=None) transparently descends through any leading
    chain of single-child, file-less folders - most notably the bare
    drive-letter segment every Windows path starts with (e.g. "C:"), but
    also e.g. a scan rooted several levels deep with no siblings along the
    way - stopping at the first level that actually branches (multiple
    folders and/or any files). Explicit navigation into a folder the user
    picked is never auto-collapsed further, so parent_path always matches
    exactly what was shown on the way down.
    """
    collapsing = folder is None
    current = folder
    while True:
        result = _browse_once(conn, disk_id, current)
        if collapsing and len(result["folders"]) == 1 and not result["files"]:
            current = result["folders"][0]["path"]
            continue
        return result
