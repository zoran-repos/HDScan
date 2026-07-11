from pathlib import Path

from file_archive.db.connection import connect
from file_archive.scanner.engine import scan_directory
from file_archive.search.query import SearchFilters, catalog_stats, find_duplicates, search_files


def _make_tree(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "docs" / "report.txt").write_text("same content")
    (root / "docs" / "report_copy.txt").write_text("same content")  # duplicate hash
    (root / "image.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpgbytes")


def _scanned_conn(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_tree(scan_root)

    db_path = tmp_path / "db" / "archive.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    scan_directory(conn, scan_root)
    return conn


def test_search_by_name_and_extension(tmp_path: Path):
    conn = _scanned_conn(tmp_path)

    results = search_files(conn, SearchFilters(name="report"))
    assert len(results) == 2

    jpgs = search_files(conn, SearchFilters(extension="jpg"))
    assert len(jpgs) == 1
    assert jpgs[0]["filename"] == "image.jpg"

    conn.close()


def test_search_by_size_range(tmp_path: Path):
    conn = _scanned_conn(tmp_path)

    huge = search_files(conn, SearchFilters(min_size=10_000_000))
    assert huge == []

    small = search_files(conn, SearchFilters(max_size=10_000_000))
    assert len(small) == 3

    conn.close()


def test_find_duplicates(tmp_path: Path):
    conn = _scanned_conn(tmp_path)

    dupes = find_duplicates(conn)
    assert len(dupes) == 1
    assert dupes[0]["copies"] == 2

    conn.close()


def test_catalog_stats(tmp_path: Path):
    conn = _scanned_conn(tmp_path)

    stats = catalog_stats(conn)
    assert stats["file_count"] == 3
    assert stats["total_bytes"] > 0
    assert len(stats["disks"]) == 1

    conn.close()
