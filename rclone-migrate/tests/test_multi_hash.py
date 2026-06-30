"""multi_hash (#10): secondary algorithms recorded alongside the primary.

Covers the single-read multi-hash primitive and the _refresh_local wiring,
including use case 3 (backfill a secondary onto an already-valid primary)."""
import io

import pytest

from rclone_migrate import cache, hashing, manifest, verbose

xxhash = pytest.importorskip("xxhash")


def _v():
    return verbose.Verbose(level=verbose.DETAIL, color=False, timestamps=False,
                           stream=io.StringIO(), err_stream=io.StringIO())


# ---- hash_file_local_multi --------------------------------------------------

def test_multi_single_read_matches_oneshot(tmp_path):
    data = b"".join(bytes([i % 256]) for i in range(200_000)) + b"tail"
    f = tmp_path / "x.bin"
    f.write_bytes(data)
    seen = []
    out = hashing.hash_file_local_multi(
        str(f), ["sha256", "md5", "xxh128"], chunk_size=64 * 1024,
        progress_cb=seen.append,
    )
    assert out["sha256"] == hashing.hash_file_local(str(f), "sha256")
    assert out["md5"] == hashing.hash_file_local(str(f), "md5")
    assert out["xxh128"] == xxhash.xxh3_128(data).hexdigest()
    # All three came from ONE shared read (progress summed to the file size once)
    assert sum(seen) == len(data)


def test_multi_dedupes_and_keeps_order(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world")
    out = hashing.hash_file_local_multi(str(f), ["md5", "md5", "sha1"])
    assert set(out) == {"md5", "sha1"}


# ---- _refresh_local extra_algos --------------------------------------------

def _refresh(root, algo, extra, tmp_path, full=False):
    return manifest._refresh_local(
        "src", str(root), algo,
        transfers=2, full=full, local_cache_in_root=True,
        fallback_dir=tmp_path / "fb", progress=False, extra_algos=extra, v=_v(),
    )


def _cache_rows(root, algo):
    conn = cache.open_db(root / ".rmig-cache.db")
    rows = cache.load_for_algorithm(conn, algo)
    conn.close()
    return rows


def test_extra_algos_cached_alongside_primary(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a" * 100)
    (root / "b.bin").write_bytes(b"b" * 200)
    m = _refresh(root, "sha256", ["md5", "xxh128"], tmp_path)
    # Manifest carries ONLY the primary algo's entries.
    assert {e.path for e in m.entries} == {"a.bin", "b.bin"}
    # ... but all three algos land in the cache for both files.
    for algo in ("sha256", "md5", "xxh128"):
        assert set(_cache_rows(root, algo)) == {"a.bin", "b.bin"}, algo
    # Digests are correct.
    assert (_cache_rows(root, "md5")["a.bin"].hash
            == hashing.hash_file_local(str(root / "a.bin"), "md5"))
    assert (_cache_rows(root, "xxh128")["b.bin"].hash
            == hashing.hash_file_local(str(root / "b.bin"), "xxh128"))


def test_extra_equal_to_primary_is_noop(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a" * 50)
    _refresh(root, "sha256", ["sha256"], tmp_path)
    # No duplicate rows / no crash; just the single primary row.
    assert set(_cache_rows(root, "sha256")) == {"a.bin"}


def test_migration_backfills_secondary_for_valid_primary(tmp_path):
    """Use case 3: a job whose primary is already cached & valid later declares
    a multi_hash — the secondary must be computed for the unchanged files even
    though the primary needs no rehash, and the primary must be left intact."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a" * 64)
    # Pass 1: primary only.
    _refresh(root, "sha256", [], tmp_path)
    assert set(_cache_rows(root, "sha256")) == {"a.bin"}
    assert set(_cache_rows(root, "sha1")) == set()  # no secondary yet
    sha256_before = _cache_rows(root, "sha256")["a.bin"].hash

    # Pass 2: add multi_hash=["sha1"], file unchanged.
    _refresh(root, "sha256", ["sha1"], tmp_path)
    # Primary untouched (same digest, not re-derived into a different row).
    assert _cache_rows(root, "sha256")["a.bin"].hash == sha256_before
    # Secondary backfilled and correct.
    assert set(_cache_rows(root, "sha1")) == {"a.bin"}
    assert (_cache_rows(root, "sha1")["a.bin"].hash
            == hashing.hash_file_local(str(root / "a.bin"), "sha1"))


def test_removed_file_drops_all_algos(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a" * 32)
    (root / "b.bin").write_bytes(b"b" * 32)
    _refresh(root, "sha256", ["md5"], tmp_path)
    assert set(_cache_rows(root, "md5")) == {"a.bin", "b.bin"}
    # Remove b.bin and refresh → its rows for BOTH algos are pruned.
    (root / "b.bin").unlink()
    _refresh(root, "sha256", ["md5"], tmp_path)
    assert set(_cache_rows(root, "sha256")) == {"a.bin"}
    assert set(_cache_rows(root, "md5")) == {"a.bin"}
