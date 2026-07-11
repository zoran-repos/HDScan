"""AppData layout for the File Archive System.

The catalog database must never live on a scanned disk, so everything is
rooted under %LOCALAPPDATA%\\FileArchiveSystem by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    db_path: Path
    thumbnails_dir: Path
    logs_dir: Path
    config_dir: Path
    backups_dir: Path
    reports_dir: Path

    def ensure(self) -> "AppPaths":
        for d in (
            self.db_path.parent,
            self.thumbnails_dir,
            self.logs_dir,
            self.config_dir,
            self.backups_dir,
            self.reports_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        return self


def get_app_paths(base_dir: Path | None = None) -> AppPaths:
    """Build (and create) the standard directory layout.

    Pass an explicit base_dir (e.g. a tmp_path) in tests to avoid touching the
    real AppData location.
    """
    if base_dir is None:
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA environment variable is not set")
        base_dir = Path(local_app_data) / "FileArchiveSystem"

    paths = AppPaths(
        base_dir=base_dir,
        db_path=base_dir / "database" / "archive.db",
        thumbnails_dir=base_dir / "thumbnails",
        logs_dir=base_dir / "logs",
        config_dir=base_dir / "config",
        backups_dir=base_dir / "backups",
        reports_dir=base_dir / "reports",
    )
    return paths.ensure()
