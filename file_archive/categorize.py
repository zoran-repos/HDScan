"""Friendly file-type categorization for reporting (Excel export, stats, etc.)."""

from __future__ import annotations

_CATEGORIES: dict[str, str] = {}


def _register(category: str, extensions: tuple[str, ...]) -> None:
    for ext in extensions:
        _CATEGORIES[ext] = category


_register("Image", (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".svg", ".ico", ".raw", ".cr2", ".nef", ".dng"))
_register("Video", (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp"))
_register("Audio", (".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus"))
_register("Book", (".epub", ".mobi", ".azw", ".azw3", ".fb2"))
_register("Document", (".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md"))
_register("Spreadsheet", (".xls", ".xlsx", ".ods", ".csv"))
_register("Presentation", (".ppt", ".pptx", ".odp"))
_register("Archive", (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"))
_register("Executable", (".exe", ".msi", ".bat", ".cmd", ".sh"))
_register("Code", (".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".html", ".css", ".json", ".xml", ".yaml", ".yml"))


def categorize(extension: str | None) -> str:
    if not extension:
        return "Other"
    return _CATEGORIES.get(extension.lower(), "Other")
