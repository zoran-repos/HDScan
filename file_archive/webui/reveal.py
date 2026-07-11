"""Open Windows Explorer with a cataloged file pre-selected.

This shells out to explorer.exe on the same machine the browser and server
are running on - it's triggered only by the user's own double-click in the
local UI, never by remote/untrusted input.
"""

from __future__ import annotations

import subprocess


def reveal_in_explorer(path: str) -> None:
    """Open Explorer with `path` selected in its containing folder.

    Uses explorer.exe's own "/select," argument convention rather than a
    plain path, which just opens the folder without highlighting the file.
    Passed as a raw command-line string (not a list) and without
    shell=True, so it goes straight to CreateProcess - no cmd.exe, no shell
    metacharacter expansion. Windows filenames can never contain a literal
    double-quote, so wrapping the path in quotes here is always safe.
    """
    subprocess.Popen(f'explorer /select,"{path}"')
