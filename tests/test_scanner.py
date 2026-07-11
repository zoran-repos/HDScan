from pathlib import Path

import pytest

from file_archive.db.connection import connect
from file_archive.scanner import engine
from file_archive.scanner.engine import scan_directory


def _make_sample_tree(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "a.txt").write_text("hello world")
    (root / "sub" / "b.txt").write_text("nested file")
    (root / "sub" / "c.bin").write_bytes(b"\x00\x01\x02\x03")


def _new_conn(tmp_path: Path):
    db_path = tmp_path / "db" / "archive.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return connect(db_path)


def test_scan_directory_catalogs_files(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    result = scan_directory(conn, scan_root)

    assert result.files_scanned == 3
    assert result.files_failed == 0

    rows = conn.execute("SELECT filename, hash FROM files ORDER BY filename").fetchall()
    assert [r["filename"] for r in rows] == ["a.txt", "b.txt", "c.bin"]
    assert all(r["hash"] for r in rows)

    conn.close()


def test_rescan_upserts_not_duplicates(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    scan_directory(conn, scan_root)
    second = scan_directory(conn, scan_root)

    assert second.files_scanned == 3
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2

    conn.close()


def test_rescan_detects_content_change(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    target = scan_root / "a.txt"
    target.write_text("version 1")

    conn = _new_conn(tmp_path)
    scan_directory(conn, scan_root)
    old_hash = conn.execute("SELECT hash FROM files WHERE filename='a.txt'").fetchone()["hash"]

    target.write_text("version 2 with substantially different content")
    scan_directory(conn, scan_root)
    new_hash = conn.execute("SELECT hash FROM files WHERE filename='a.txt'").fetchone()["hash"]

    assert old_hash != new_hash
    conn.close()


def test_scan_missing_path_raises(tmp_path: Path):
    conn = _new_conn(tmp_path)
    try:
        with pytest.raises(FileNotFoundError):
            scan_directory(conn, tmp_path / "does_not_exist")
    finally:
        conn.close()


def test_hash_mode_none_skips_hashing(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    scan_directory(conn, scan_root, hash_mode="none")

    rows = conn.execute("SELECT hash, hash_algo FROM files").fetchall()
    assert all(r["hash"] is None and r["hash_algo"] is None for r in rows)
    conn.close()


def test_invalid_hash_mode_rejected(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            scan_directory(conn, scan_root, hash_mode="bogus")
    finally:
        conn.close()


def test_rescan_skips_hashing_unchanged_files(tmp_path: Path, monkeypatch):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    scan_directory(conn, scan_root)
    first_hashes = {
        r["filename"]: r["hash"]
        for r in conn.execute("SELECT filename, hash FROM files").fetchall()
    }

    calls = []
    original_hash_file = engine.hash_file

    def spy_hash_file(path, size, mode="sampled"):
        calls.append(path)
        return original_hash_file(path, size, mode=mode)

    monkeypatch.setattr(engine, "hash_file", spy_hash_file)

    second = scan_directory(conn, scan_root)

    assert second.files_scanned == 3
    assert calls == []  # nothing changed - no file should have been re-hashed

    second_hashes = {
        r["filename"]: r["hash"]
        for r in conn.execute("SELECT filename, hash FROM files").fetchall()
    }
    assert second_hashes == first_hashes
    conn.close()


def test_rescan_still_hashes_changed_file_only(tmp_path: Path, monkeypatch):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    scan_directory(conn, scan_root)

    (scan_root / "a.txt").write_text("completely different content now")

    calls = []
    original_hash_file = engine.hash_file

    def spy_hash_file(path, size, mode="sampled"):
        calls.append(Path(path).name)
        return original_hash_file(path, size, mode=mode)

    monkeypatch.setattr(engine, "hash_file", spy_hash_file)

    scan_directory(conn, scan_root)
    assert calls == ["a.txt"]  # only the changed file was re-hashed
    conn.close()


def test_ctrl_c_saves_progress_and_marks_scan_interrupted(tmp_path: Path, monkeypatch):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)

    original_hash_file = engine.hash_file

    def interrupting_hash_file(path, size, mode="sampled"):
        if Path(path).name == "c.bin":
            raise KeyboardInterrupt()
        return original_hash_file(path, size, mode=mode)

    monkeypatch.setattr(engine, "hash_file", interrupting_hash_file)

    with pytest.raises(KeyboardInterrupt):
        scan_directory(conn, scan_root)

    # a.txt is walked before the "sub" subdirectory that contains c.bin, so
    # it must already be saved even though the scan never finished.
    filenames = {r["filename"] for r in conn.execute("SELECT filename FROM files").fetchall()}
    assert "a.txt" in filenames
    assert "c.bin" not in filenames

    scan_row = conn.execute("SELECT status FROM scans ORDER BY scan_id DESC LIMIT 1").fetchone()
    assert scan_row["status"] == "interrupted"

    conn.close()


def test_interrupted_scan_marked_on_next_run(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    _make_sample_tree(scan_root)

    conn = _new_conn(tmp_path)
    result = scan_directory(conn, scan_root)

    # Simulate a process that died mid-scan: a scans row stuck at 'running'.
    conn.execute(
        "UPDATE scans SET status='running', finished_at=NULL WHERE scan_id=?",
        (result.scan_id,),
    )

    scan_directory(conn, scan_root)

    status = conn.execute(
        "SELECT status FROM scans WHERE scan_id=?", (result.scan_id,)
    ).fetchone()["status"]
    assert status == "interrupted"
    conn.close()
