from pathlib import Path

from file_archive.db.connection import connect
from file_archive.scanner.engine import scan_directory
from file_archive.webui.tree import browse, list_disks, update_disk


def _scanned_conn(tmp_path: Path):
    scan_root = tmp_path / "data"
    scan_root.mkdir()
    (scan_root / "Knjige").mkdir()
    (scan_root / "Knjige" / "roman.epub").write_text("book")
    (scan_root / "Slike").mkdir()
    (scan_root / "Slike" / "Odmor").mkdir()
    (scan_root / "Slike" / "Odmor" / "plaza.jpg").write_bytes(b"jpgdata")
    (scan_root / "belezni.txt").write_text("top level note")

    db_path = tmp_path / "db" / "archive.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    scan_directory(conn, scan_root)
    return conn, scan_root


def test_list_disks_returns_one_disk_with_counts(tmp_path: Path):
    conn, _ = _scanned_conn(tmp_path)
    disks = list_disks(conn)
    assert len(disks) == 1
    assert disks[0]["file_count"] == 3
    conn.close()


def test_root_browse_auto_collapses_drive_letter(tmp_path: Path):
    conn, scan_root = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    result = browse(conn, disk_id, None)

    # current_path should already be past the bare drive-letter segment
    assert not result["current_path"].rstrip("\\").endswith(":")
    names = {f["name"] for f in result["folders"]}
    assert "Knjige" in names or any(scan_root.name in result["current_path"] for _ in [1])
    conn.close()


def test_browse_lists_direct_children_only(tmp_path: Path):
    conn, scan_root = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    result = browse(conn, disk_id, str(scan_root))

    folder_names = {f["name"] for f in result["folders"]}
    file_names = {f["name"] for f in result["files"]}
    assert folder_names == {"Knjige", "Slike"}
    assert file_names == {"belezni.txt"}

    knjige = next(f for f in result["folders"] if f["name"] == "Knjige")
    assert knjige["file_count"] == 1

    conn.close()


def test_browse_descends_into_nested_folder(tmp_path: Path):
    conn, scan_root = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    slike = str(scan_root / "Slike")
    result = browse(conn, disk_id, slike)
    assert [f["name"] for f in result["folders"]] == ["Odmor"]
    assert result["files"] == []

    odmor = str(scan_root / "Slike" / "Odmor")
    result2 = browse(conn, disk_id, odmor)
    assert result2["folders"] == []
    assert [f["name"] for f in result2["files"]] == ["plaza.jpg"]
    assert result2["files"][0]["category"] == "Image"

    conn.close()


def test_parent_path_navigation(tmp_path: Path):
    conn, scan_root = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    odmor = str(scan_root / "Slike" / "Odmor")
    result = browse(conn, disk_id, odmor)
    assert result["parent_path"] is not None
    assert result["parent_path"].endswith("Slike")

    slike = str(scan_root / "Slike")
    result2 = browse(conn, disk_id, slike)
    # Slike is one level below the auto-collapsed root - going up from it
    # should land back at that (implicit) root, not expose a bare "C:".
    if result2["parent_path"] is not None:
        assert not result2["parent_path"].rstrip("\\").endswith(":")

    conn.close()


def test_update_disk_sets_label_and_description(tmp_path: Path):
    conn, _ = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    update_disk(conn, disk_id, label="Moj Backup Disk", description="Fotografije i knjige")

    disk = list_disks(conn)[0]
    assert disk["label"] == "Moj Backup Disk"
    assert disk["description"] == "Fotografije i knjige"
    conn.close()


def test_update_disk_only_touches_passed_fields(tmp_path: Path):
    conn, _ = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    update_disk(conn, disk_id, label="Prvi Naziv", description="Prvi opis")
    update_disk(conn, disk_id, label="Drugi Naziv")  # description not passed - should survive

    disk = list_disks(conn)[0]
    assert disk["label"] == "Drugi Naziv"
    assert disk["description"] == "Prvi opis"
    conn.close()


def test_rescan_does_not_clobber_custom_label(tmp_path: Path):
    conn, scan_root = _scanned_conn(tmp_path)
    disk_id = list_disks(conn)[0]["disk_id"]

    update_disk(conn, disk_id, label="Moj Prilagodjeni Naziv", description="ne diraj ovo")

    scan_directory(conn, scan_root)  # re-scan the same disk

    disk = list_disks(conn)[0]
    assert disk["label"] == "Moj Prilagodjeni Naziv"
    assert disk["description"] == "ne diraj ovo"
    conn.close()
