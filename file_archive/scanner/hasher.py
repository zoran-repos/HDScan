from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MB

HASH_ALGO_FULL = "blake2b"
HASH_ALGO_SAMPLED = "blake2b-sampled"

# Files at or below this size are always fully hashed - the read is cheap
# either way, so there's no reason to trade accuracy for speed.
LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB

# For files above the threshold, only this many bytes are read from the
# start and end of the file (plus the exact size) instead of the whole
# thing. This is dramatically faster for large video/photo collections on
# slow drives, at the cost of a (in practice very small) chance of treating
# two same-sized files that differ only in their untouched middle section
# as duplicates.
SAMPLE_SIZE = 1024 * 1024  # 1 MB from head and 1 MB from tail


def hash_file_full(path: Path) -> str:
    digest = hashlib.blake2b()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_file_sampled(path: Path, size: int) -> str:
    digest = hashlib.blake2b()
    digest.update(size.to_bytes(8, "big"))
    with open(path, "rb") as f:
        digest.update(f.read(SAMPLE_SIZE))
        if size > SAMPLE_SIZE:
            f.seek(max(size - SAMPLE_SIZE, 0))
            digest.update(f.read(SAMPLE_SIZE))
    return digest.hexdigest()


def hash_file(path: Path, size: int, mode: str = "sampled") -> tuple[str, str] | tuple[None, None]:
    """Compute a content hash according to mode.

    mode:
      - "none": skip hashing entirely (fastest, no duplicate detection)
      - "full": always read the entire file (slowest, exact)
      - "sampled": full hash for files <= LARGE_FILE_THRESHOLD, head+tail+size
        sample for anything larger (default - fast on large media collections)

    Returns (hash_hex, algo_label), or (None, None) if mode == "none".
    """
    if mode == "none":
        return None, None
    if mode == "full" or size <= LARGE_FILE_THRESHOLD:
        return hash_file_full(path), HASH_ALGO_FULL
    if mode == "sampled":
        return hash_file_sampled(path, size), HASH_ALGO_SAMPLED
    raise ValueError(f"Unknown hash mode: {mode!r}")
