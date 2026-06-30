import hashlib
import shutil
from pathlib import Path
from unittest import mock

import pytest

from rclone_migrate import hashing


def test_normalize():
    assert hashing.normalize("MD5") == "md5"
    assert hashing.normalize("SHA-256") == "sha256"
    assert hashing.normalize("sha1") == "sha1"


def test_hash_file_local_md5(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    expected = hashlib.md5(b"hello world").hexdigest()
    assert hashing.hash_file_local(str(f), "md5") == expected


def test_hash_file_local_sha256(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert hashing.hash_file_local(str(f), "sha256") == expected


xxhash = pytest.importorskip("xxhash")


def test_can_stream_local_truth_table():
    for a in ("md5", "sha1", "sha256", "sha512", "xxh3", "xxh128", "xxh64"):
        assert hashing.can_stream_local(a) is True
    for a in ("crc32", "blake3", "quickxor", "whirlpool"):
        assert hashing.can_stream_local(a) is False


def test_hash_file_local_xxhash_streams_and_matches_oneshot(tmp_path: Path):
    data = b"".join(bytes([i % 256]) for i in range(300_000)) + b"end"
    f = tmp_path / "x.bin"
    f.write_bytes(data)
    cases = {
        "xxh3": xxhash.xxh3_64(data).hexdigest(),
        "xxh128": xxhash.xxh3_128(data).hexdigest(),
        "xxh64": xxhash.xxh64(data).hexdigest(),
    }
    for algo, expected in cases.items():
        seen = []
        got = hashing.hash_file_local(
            str(f), algo, chunk_size=64 * 1024, progress_cb=seen.append
        )
        assert got == expected, algo
        assert sum(seen) == len(data)        # progress_cb fired per chunk
        assert len(seen) >= 4


@pytest.mark.skipif(shutil.which("rclone") is None, reason="rclone not installed")
def test_xxhash_digest_byte_identical_to_rclone(tmp_path: Path):
    """Critical: a manifest hashed in-process must match a side hashed by
    rclone, or check/copy would see false 'missing' files."""
    import subprocess

    f = tmp_path / "blob.bin"
    f.write_bytes(b"rclone-parity-check" * 9999)
    for algo in ("xxh3", "xxh128"):
        out = subprocess.run(
            ["rclone", "hashsum", algo, str(f)],
            capture_output=True, text=True, check=True,
        ).stdout.split()[0]
        assert hashing.hash_file_local(str(f), algo) == out, algo


def test_negotiate_picks_strongest_common(monkeypatch):
    def fake(path):
        return {
            "/local/src": ["md5", "sha1", "sha256", "sha512"],
            "remote:dst": ["md5"],
        }[path]
    monkeypatch.setattr(hashing, "supported_hashes", fake)
    assert hashing.negotiate("/local/src", "remote:dst") == "md5"


def test_negotiate_local_to_local_picks_sha256(monkeypatch):
    def fake(path):
        return ["md5", "sha1", "sha256", "sha512", "blake3"]
    monkeypatch.setattr(hashing, "supported_hashes", fake)
    assert hashing.negotiate("/a", "/b") == "sha256"


def test_negotiate_b2_picks_sha1(monkeypatch):
    def fake(path):
        return {
            "/local/src": ["md5", "sha1", "sha256", "sha512"],
            "b2:bucket":  ["sha1"],
        }[path]
    monkeypatch.setattr(hashing, "supported_hashes", fake)
    assert hashing.negotiate("/local/src", "b2:bucket") == "sha1"


def test_negotiate_override_must_be_supported(monkeypatch):
    # Remote paths: effective_supported == advertised only, so an unadvertised
    # override still raises (local sides are augmented — see #75 tests below).
    def fake(path):
        return ["md5"]
    monkeypatch.setattr(hashing, "supported_hashes", fake)
    with pytest.raises(hashing.HashNegotiationError):
        hashing.negotiate("remote:a", "remote:b", override="sha256")


def test_negotiate_override_works(monkeypatch):
    def fake(path):
        return ["md5", "sha1", "sha256"]
    monkeypatch.setattr(hashing, "supported_hashes", fake)
    assert hashing.negotiate("a", "b", override="MD5") == "md5"


def test_negotiate_no_common(monkeypatch):
    # Remote↔remote with disjoint advertised sets — no in-process augmentation.
    def fake(path):
        return {"remote:a": ["md5"], "remote:b": ["sha256"]}[path]
    monkeypatch.setattr(hashing, "supported_hashes", fake)
    with pytest.raises(hashing.HashNegotiationError):
        hashing.negotiate("remote:a", "remote:b")


# --- local-side in-process hashing folds into negotiation (#75) ---------------

def test_effective_supported_local_adds_streamable(monkeypatch):
    """A local path offers rclone-advertised hashes PLUS what rmig streams
    in-process (hashlib + xxhash), even if rclone's local backend doesn't
    advertise them (it doesn't advertise xxh128)."""
    monkeypatch.setattr(hashing, "supported_hashes",
                        lambda p: ["md5", "sha1", "sha256", "crc32"])
    eff = hashing.effective_supported("/mnt/nas/raw")
    assert "xxh128" in eff and "xxh3" in eff   # via internal hasher
    assert "crc32" in eff                       # advertised-only still present


def test_effective_supported_remote_advertised_only(monkeypatch):
    """Remote paths are NOT augmented — rmig can't hash bytes it doesn't hold
    (the remote-download decoupling is tracked separately, D2 follow-up)."""
    monkeypatch.setattr(hashing, "supported_hashes", lambda p: ["sha1"])
    eff = hashing.effective_supported("b2:bucket")
    assert eff == {"sha1"}
    assert "xxh128" not in eff


def test_negotiate_local_override_xxh128_without_backend_advertise(monkeypatch):
    """Regression (#75): local↔local job pinned to xxh128 must negotiate even
    though the rclone local backend advertises no xxh128. This was the
    HashNegotiationError that aborted `rmig check`/`hash` before any work."""
    rclone_local = ["md5", "sha1", "whirlpool", "crc32", "sha256",
                    "dropbox", "hidrive", "mailru", "quickxor"]  # real local set
    monkeypatch.setattr(hashing, "supported_hashes", lambda p: rclone_local)
    assert hashing.negotiate("/a", "/b", override="xxh128") == "xxh128"


def test_negotiate_remote_override_xxh128_still_raises(monkeypatch):
    """D2 scope guard: a remote side that can't natively produce xxh128 still
    raises — the local augmentation must not leak to remotes."""
    monkeypatch.setattr(hashing, "supported_hashes",
                        lambda p: ["md5", "sha1", "sha256"])
    with pytest.raises(hashing.HashNegotiationError):
        hashing.negotiate("/local/src", "sftp:host/path", override="xxh128")


def test_negotiate_local_auto_unchanged_still_sha256(monkeypatch):
    """Augmentation must not change auto-negotiation: sha256 still wins for
    local↔local (PREFERRED_ORDER), xxh* only reachable via explicit override."""
    rclone_local = ["md5", "sha1", "sha256", "crc32", "whirlpool"]
    monkeypatch.setattr(hashing, "supported_hashes", lambda p: rclone_local)
    assert hashing.negotiate("/a", "/b") == "sha256"
