"""Stable disk identity via the Windows volume serial number.

The volume serial (not the drive letter) is used as the catalog's disk
identity, so re-scanning the same physical disk after it gets remounted to a
different drive letter still matches the existing `disks` row.
"""

from __future__ import annotations

import ctypes
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VolumeInfo:
    serial: str
    label: str
    filesystem: str
    total_bytes: int


def _volume_root(path: Path) -> str:
    drive = Path(path).resolve().drive  # e.g. "C:"
    if not drive:
        raise ValueError(f"Cannot determine drive letter for path: {path}")
    return drive + "\\"


def get_volume_info(path: Path) -> VolumeInfo:
    root = _volume_root(path)

    volume_name_buf = ctypes.create_unicode_buffer(261)
    filesystem_buf = ctypes.create_unicode_buffer(261)
    serial_number = ctypes.c_ulong(0)
    max_component_len = ctypes.c_ulong(0)
    filesystem_flags = ctypes.c_ulong(0)

    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root),
        volume_name_buf,
        ctypes.sizeof(volume_name_buf),
        ctypes.byref(serial_number),
        ctypes.byref(max_component_len),
        ctypes.byref(filesystem_flags),
        filesystem_buf,
        ctypes.sizeof(filesystem_buf),
    )
    if not ok:
        raise OSError(
            f"GetVolumeInformationW failed for {root!r} "
            f"(error {ctypes.get_last_error()})"
        )

    total_bytes = shutil.disk_usage(root).total

    return VolumeInfo(
        serial=f"{serial_number.value:08X}",
        label=volume_name_buf.value or root,
        filesystem=filesystem_buf.value,
        total_bytes=total_bytes,
    )
