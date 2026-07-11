from pathlib import Path

from file_archive.scanner.hasher import (
    HASH_ALGO_FULL,
    HASH_ALGO_SAMPLED,
    LARGE_FILE_THRESHOLD,
    SAMPLE_SIZE,
    hash_file,
)


def test_none_mode_skips_hashing(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    file_hash, algo = hash_file(f, f.stat().st_size, mode="none")
    assert file_hash is None
    assert algo is None


def test_small_file_is_always_fully_hashed_even_in_sampled_mode(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("small file well under the threshold")
    size = f.stat().st_size

    full_hash, full_algo = hash_file(f, size, mode="full")
    sampled_hash, sampled_algo = hash_file(f, size, mode="sampled")

    assert full_algo == HASH_ALGO_FULL
    assert sampled_algo == HASH_ALGO_FULL  # below threshold -> sampled falls back to full
    assert full_hash == sampled_hash


def test_large_file_uses_sampled_algo_and_differs_from_full(tmp_path: Path):
    f = tmp_path / "big.bin"
    size = LARGE_FILE_THRESHOLD + SAMPLE_SIZE * 3
    with open(f, "wb") as fh:
        fh.seek(size - 1)
        fh.write(b"\0")

    full_hash, full_algo = hash_file(f, size, mode="full")
    sampled_hash, sampled_algo = hash_file(f, size, mode="sampled")

    assert full_algo == HASH_ALGO_FULL
    assert sampled_algo == HASH_ALGO_SAMPLED
    assert full_hash != sampled_hash  # different inputs, different digests


def test_sampled_hash_is_stable_for_same_head_tail_and_size(tmp_path: Path):
    size = LARGE_FILE_THRESHOLD + SAMPLE_SIZE * 2

    f1 = tmp_path / "one.bin"
    with open(f1, "wb") as fh:
        fh.write(b"A" * SAMPLE_SIZE)
        fh.seek(size - SAMPLE_SIZE)
        fh.write(b"Z" * SAMPLE_SIZE)

    f2 = tmp_path / "two.bin"
    with open(f2, "wb") as fh:
        fh.write(b"A" * SAMPLE_SIZE)
        fh.seek(size - SAMPLE_SIZE)
        fh.write(b"Z" * SAMPLE_SIZE)

    hash1, _ = hash_file(f1, size, mode="sampled")
    hash2, _ = hash_file(f2, size, mode="sampled")
    assert hash1 == hash2  # identical head+tail+size -> same sampled hash by design
