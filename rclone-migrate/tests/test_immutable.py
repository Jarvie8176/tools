"""UF_IMMUTABLE (macOS `uchg`) handling in copy (#54).

The detection/clear helpers are Linux-safe no-ops (no `st_flags`/`os.chflags`),
so they run everywhere; the real `uchg` behavior is exercised on macOS/BSD only
(the self-hosted mac CI lane) via a skipif guard."""
import io
import os
import stat

import pytest

from rclone_migrate import config as config_mod, manifest, ops, verbose

_HAS_CHFLAGS = hasattr(os, "chflags")
mac_only = pytest.mark.skipif(not _HAS_CHFLAGS, reason="macOS/BSD only (chflags)")


def _v():
    return verbose.Verbose(level=verbose.DETAIL, color=False, timestamps=False,
                           stream=io.StringIO(), err_stream=io.StringIO())


# ---- helpers: Linux-safe no-ops (run everywhere) ---------------------------

def test_is_immutable_false_for_normal_file(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    assert ops._is_immutable(str(f)) is False       # no uchg / no st_flags


def test_is_immutable_false_for_missing_file(tmp_path):
    assert ops._is_immutable(str(tmp_path / "nope")) is False


def test_clear_immutable_is_safe_on_normal_file(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    ops._clear_immutable(str(f))                     # must not raise anywhere
    assert f.exists()


def test_clean_stale_partials_removes_normal_partial(tmp_path):
    dst = tmp_path / "dst"
    dst.mkdir()
    p = dst / "a.bin.deadbeef.partial"
    p.write_bytes(b"x")
    job = config_mod.Job(name="j", src=str(tmp_path / "src"), dst=str(dst))
    to_copy = [manifest.Entry(path="a.bin", hash="h", size=1)]
    assert ops._clean_stale_partials(job, to_copy, _v()) == 1
    assert not p.exists()


# ---- real uchg behavior: macOS/BSD only ------------------------------------

@mac_only
def test_is_immutable_detects_and_clears_uchg(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    os.chflags(str(f), stat.UF_IMMUTABLE)
    try:
        assert ops._is_immutable(str(f)) is True
        ops._clear_immutable(str(f))
        assert ops._is_immutable(str(f)) is False
    finally:
        os.chflags(str(f), 0)                        # ensure cleanup


@mac_only
def test_clean_stale_partials_clears_uchg_partial(tmp_path):
    """A stale `.partial` carrying uchg must be cleared + removed, not EPERM."""
    dst = tmp_path / "dst"
    dst.mkdir()
    p = dst / "a.bin.deadbeef.partial"
    p.write_bytes(b"x")
    os.chflags(str(p), stat.UF_IMMUTABLE)
    job = config_mod.Job(name="j", src=str(tmp_path / "src"), dst=str(dst))
    to_copy = [manifest.Entry(path="a.bin", hash="h", size=1)]
    try:
        assert ops._clean_stale_partials(job, to_copy, _v()) == 1
        assert not p.exists()
    finally:
        if p.exists():
            os.chflags(str(p), 0)
