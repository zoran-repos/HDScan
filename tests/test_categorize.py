from file_archive.categorize import categorize


def test_known_categories():
    assert categorize(".jpg") == "Image"
    assert categorize(".JPG") == "Image"
    assert categorize(".epub") == "Book"
    assert categorize(".mp4") == "Video"
    assert categorize(".mp3") == "Audio"
    assert categorize(".pdf") == "Document"
    assert categorize(".zip") == "Archive"


def test_unknown_or_missing_extension_is_other():
    assert categorize(".xyz123") == "Other"
    assert categorize(None) == "Other"
    assert categorize("") == "Other"
