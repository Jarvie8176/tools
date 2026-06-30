"""MHL emit correctness (#82): per-file action (original/verified/failed)
against the previous generation, parse_manifest round-trip, system-junk
exclusion from the walk, and creator-metadata consistency across generations."""
import io
import re

from rclone_migrate import cache, config as config_mod, manifest, mhl, ops, verbose


def _v():
    return verbose.Verbose(level=verbose.DETAIL, color=False, timestamps=False,
                           stream=io.StringIO(), err_stream=io.StringIO())


def _emit(cfg, job, rows, *, algo="sha1", action="original"):
    ents = [manifest.Entry(path=p, hash=h, size=s) for (p, h, s) in rows]
    return ops.emit_mhl_generation(
        cfg, job, "src", entries=ents, algorithm=algo,
        process="in-place", action=action, v=_v(),
    )


def _latest_actions(root, algo):
    d = root / "ascmhl"
    latest = max(d.glob("*.mhl"),
                 key=lambda p: int(re.match(r"(\d+)_", p.name).group(1)))
    return {e.path: e.actions.get(algo)
            for e in mhl.parse_manifest(latest.read_bytes())}


# ---- system-junk exclusion (#82 P2) ----------------------------------------

def test_system_junk_helpers():
    assert ".fseventsd" in cache.SYSTEM_JUNK_DIRS
    assert cache.is_system_junk_file(".DS_Store")
    assert cache.is_system_junk_file("._ascmhl")        # AppleDouble of a junk dir
    assert cache.is_system_junk_file("._.DS_Store")
    assert not cache.is_system_junk_file("._VID_0001.insv")  # real media → keep
    assert not cache.is_system_junk_file("photo.jpg")


def test_refresh_local_excludes_system_junk(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    (root / "real.bin").write_bytes(b"x" * 8)
    (root / ".DS_Store").write_bytes(b"junk")
    (root / "._ascmhl").write_bytes(b"\x00")             # the #19 leak
    fse = root / ".fseventsd"
    fse.mkdir()
    (fse / "0000000000000001").write_bytes(b"e")
    m = manifest._refresh_local(
        "src", str(root), "sha256", transfers=1, full=False,
        local_cache_in_root=True, fallback_dir=tmp_path / "fb",
        progress=False, v=_v(),
    )
    paths = {e.path for e in m.entries}
    assert "real.bin" in paths
    assert ".DS_Store" not in paths
    assert "._ascmhl" not in paths
    assert not any(p.startswith(".fseventsd") for p in paths)


# ---- parse_manifest round-trip ---------------------------------------------

def test_parse_manifest_round_trip():
    gen = mhl.Generation(
        sequencenr=1, process="in-place",
        creator=mhl.CreatorInfo.default(),
        entries=[
            mhl.HashEntry(path="a.bin", size=3, hashes={"sha1": "aaa"},
                          actions={"sha1": "original"}),
            mhl.HashEntry(path="sub/b.bin", size=5, hashes={"sha1": "bbb"},
                          actions={"sha1": "verified"}),
        ],
    )
    parsed = mhl.parse_manifest(mhl.render_manifest(gen))
    got = {e.path: (e.hashes["sha1"], e.actions.get("sha1")) for e in parsed}
    assert got == {"a.bin": ("aaa", "original"), "sub/b.bin": ("bbb", "verified")}


# ---- action semantics across generations (#82 P0) --------------------------

def test_action_original_then_verified_then_failed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    cfg = config_mod.Config(defaults=config_mod.Defaults())
    job = config_mod.Job(name="j", src=str(src), dst=str(tmp_path / "d"))

    # Gen 1 — both files brand new → original.
    _emit(cfg, job, [("a.bin", "aaa", 3), ("b.bin", "bbb", 3)])
    assert _latest_actions(src, "sha1") == {"a.bin": "original", "b.bin": "original"}

    # Gen 2 — identical hashes → verified (the bug: was always "original").
    _emit(cfg, job, [("a.bin", "aaa", 3), ("b.bin", "bbb", 3)])
    assert _latest_actions(src, "sha1") == {"a.bin": "verified", "b.bin": "verified"}

    # Gen 3 — a changed (failed), b unchanged (verified), c new (original).
    _emit(cfg, job, [("a.bin", "zzz", 3), ("b.bin", "bbb", 3), ("c.bin", "ccc", 3)])
    assert _latest_actions(src, "sha1") == {
        "a.bin": "failed", "b.bin": "verified", "c.bin": "original",
    }


def test_new_file_uses_caller_action(tmp_path):
    """A genuinely-new file (absent from the prior generation) takes the
    caller's action — so a copy/transfer's fresh dst files stay 'original'."""
    src = tmp_path / "src"
    src.mkdir()
    cfg = config_mod.Config(defaults=config_mod.Defaults())
    job = config_mod.Job(name="j", src=str(src), dst=str(tmp_path / "d"))
    _emit(cfg, job, [("a.bin", "aaa", 3)], action="original")
    _emit(cfg, job, [("a.bin", "aaa", 3), ("new.bin", "nnn", 3)], action="original")
    acts = _latest_actions(src, "sha1")
    assert acts["a.bin"] == "verified"   # seen before, matches
    assert acts["new.bin"] == "original"  # new this generation


# ---- creator metadata consistency (#82 P1) ---------------------------------

def test_creator_metadata_consistent_across_generations(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    cfg = config_mod.Config(defaults=config_mod.Defaults(
        mhl_author="Me <me@example.com>", mhl_location="Home Studio",
        mhl_author_role="DIT",
    ))
    job = config_mod.Job(name="j", src=str(src), dst=str(tmp_path / "d"))
    _emit(cfg, job, [("a.bin", "aaa", 3)])
    _emit(cfg, job, [("a.bin", "aaa", 3)])
    gens = sorted((src / "ascmhl").glob("*.mhl"))
    assert len(gens) == 2
    for g in gens:                       # no regression: both carry full creator
        x = g.read_text()
        assert "Me" in x and "me@example.com" in x
        assert "Home Studio" in x and "DIT" in x
