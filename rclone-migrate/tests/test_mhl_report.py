"""MHL report hash decoupled from transfer primary (#83): the MHL generation
records `mhl_hash` (e.g. xxh64, computed as a secondary), not the negotiated
transfer algo. Plus the xxh64 big-endian canonical lock."""
import io
import re

import pytest

from rclone_migrate import (
    config as config_mod, hashing, manifest, mhl, ops, profiles, verbose,
)

pytest.importorskip("xxhash")


def _v():
    return verbose.Verbose(level=verbose.DETAIL, color=False, timestamps=False,
                           stream=io.StringIO(), err_stream=io.StringIO())


# ---- xxh64 big-endian canonical lock (#83 critical) ------------------------

def test_xxh64_is_big_endian_canonical(tmp_path):
    """rmig's xxh64 hexdigest MUST be the canonical big-endian value, or
    Silverstack/YoYotta silently reject the MHL. XXH64("") = ef46db3751d8e999
    is the documented reference vector (big-endian). A little-endian lib would
    emit the byte-reversed 99e9d85137db46ef."""
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert hashing.hash_file_local(str(f), "xxh64") == "ef46db3751d8e999"


# ---- profile / config resolution -------------------------------------------

def test_dit_profile_declares_mhl_hash_xxh64():
    prof = profiles.load("dit")
    assert prof.mhl_hash == "xxh64"
    assert prof.priority[0] == "xxh128"   # transfer stays fast/native


def test_resolve_mhl_hash_precedence(tmp_path):
    # profile provides it; [defaults] and job override in turn.
    cfg = config_mod.Config(defaults=config_mod.Defaults())
    job = config_mod.Job(name="j", src="/s", dst="/d", hash_profile="dit")
    assert cfg.resolve_mhl_hash(job) == "xxh64"          # from profile
    cfg2 = config_mod.Config(defaults=config_mod.Defaults(mhl_hash="sha1"))
    assert cfg2.resolve_mhl_hash(job) == "sha1"          # defaults > profile
    job.mhl_hash = "md5"
    assert cfg2.resolve_mhl_hash(job) == "md5"           # job > defaults


def test_emit_mhl_ok_with_non_mhl_primary_when_mhl_hash_set(tmp_path):
    """emit_mhl=true + sha256 primary (not MHL-valid) must NOT error when
    mhl_hash provides an MHL algo — the primary/transfer is decoupled."""
    cfg = config_mod.Config(defaults=config_mod.Defaults(
        emit_mhl=True, mhl_hash="xxh64", hash_priority=["sha256"]))
    job = config_mod.Job(name="j", src="/s", dst="/d")
    # sha256 stays as the transfer priority (not filtered away).
    assert cfg.resolve_priority(job) == ["sha256"]


# ---- emit records the report algo from cache -------------------------------

def _refresh(root, algo, extra, tmp_path):
    return manifest._refresh_local(
        "src", str(root), algo, transfers=1, full=False,
        local_cache_in_root=True, fallback_dir=tmp_path / "fb",
        extra_algos=extra, progress=False, v=_v())


def _latest(root):
    d = root / "ascmhl"
    latest = max(d.glob("*.mhl"),
                 key=lambda p: int(re.match(r"(\d+)_", p.name).group(1)))
    return {e.path: e.hashes for e in mhl.parse_manifest(latest.read_bytes())}


def test_emit_records_mhl_hash_not_primary(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"alpha")
    # transfer primary = sha1; report secondary = xxh64 (both computed).
    m = _refresh(root, "sha1", ["xxh64"], tmp_path)
    cfg = config_mod.Config(defaults=config_mod.Defaults(mhl_hash="xxh64"))
    job = config_mod.Job(name="j", src=str(root), dst=str(tmp_path / "d"),
                         local_cache_in_root=True)
    p = ops.emit_mhl_generation(cfg, job, "src", entries=m.entries,
                                algorithm="sha1", process="in-place",
                                action="original", v=_v())
    assert p is not None
    hashes = _latest(root)["a.bin"]
    assert "xxh64" in hashes and "sha1" not in hashes      # report=xxh64, not primary
    assert hashes["xxh64"] == hashing.hash_file_local(str(root / "a.bin"), "xxh64")


def test_emit_falls_back_to_primary_when_no_mhl_hash(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"alpha")
    m = _refresh(root, "sha1", [], tmp_path)
    cfg = config_mod.Config(defaults=config_mod.Defaults())   # no mhl_hash
    job = config_mod.Job(name="j", src=str(root), dst=str(tmp_path / "d"),
                         local_cache_in_root=True)
    ops.emit_mhl_generation(cfg, job, "src", entries=m.entries,
                            algorithm="sha1", process="in-place",
                            action="original", v=_v())
    assert "sha1" in _latest(root)["a.bin"]                # legacy: primary emitted


def test_emit_falls_back_to_mhl_valid_primary_when_report_uncached(tmp_path):
    """Report algo not computed (e.g. copy/check) but the primary IS MHL-valid
    → record the primary rather than skip. (`rmig hash` computes the report.)"""
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"alpha")
    m = _refresh(root, "sha1", [], tmp_path)              # sha1 primary, no xxh64
    cfg = config_mod.Config(defaults=config_mod.Defaults(mhl_hash="xxh64"))
    job = config_mod.Job(name="j", src=str(root), dst=str(tmp_path / "d"),
                         local_cache_in_root=True)
    p = ops.emit_mhl_generation(cfg, job, "src", entries=m.entries,
                                algorithm="sha1", process="in-place",
                                action="original", v=_v())
    assert p is not None
    assert "sha1" in _latest(root)["a.bin"]              # fell back to primary


def test_emit_skips_when_report_uncached_and_primary_not_mhl(tmp_path):
    """Report algo uncached AND primary (sha256) not MHL-valid → skip."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.bin").write_bytes(b"alpha")
    m = _refresh(root, "sha256", [], tmp_path)           # sha256 ∉ MHL set, no xxh64
    cfg = config_mod.Config(defaults=config_mod.Defaults(mhl_hash="xxh64"))
    job = config_mod.Job(name="j", src=str(root), dst=str(tmp_path / "d"),
                         local_cache_in_root=True)
    p = ops.emit_mhl_generation(cfg, job, "src", entries=m.entries,
                                algorithm="sha256", process="in-place",
                                action="original", v=_v())
    assert p is None                                      # skipped, warned
    assert not (root / "ascmhl").exists() or not list((root / "ascmhl").glob("*.mhl"))
