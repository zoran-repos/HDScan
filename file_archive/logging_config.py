from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(logs_dir: Path, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("file_archive")
    if logger.handlers:
        return logger  # already configured (e.g. re-entrant CLI calls, tests)

    logger.setLevel(level)

    file_handler = RotatingFileHandler(
        logs_dir / "file_archive.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(console_handler)

    return logger
