"""Tests for src manifest CSV emit (issue #55)."""
from __future__ import annotations

import csv
import io

from rclone_migrate import cache, src_manifest, verbose
from rclone_migrate.manifest import Entry, Manifest


def _v() -> verbose.Verbose:
    """A Verbose that captures both streams so warn/info don't pollute pytest."""
    return verbose.Verbose(
        level=verbose.DETAIL,
        color=False,
        timestamps=False,
        stream=io.StringIO(),
        err_stream=io.StringIO(),
    )


def _mf(side: str, root: str, entries: list[Entry], algo: str = "sha256") -> Manifest:
    m = Manifest(side, root, algo)
    m.entries = entries
    return m


# --- compute_rows: pure logic ----------------------------------------------

def test_dedup_status_kept_when_unique_hash():
    src = _mf("src", "/src", [
        Entry("a.bin", "h1", 100),
        Entry("b.bin", "h2", 200),
    ])
    dst = _mf("dst", "/dst", [])
    rows = src_manifest.compute_rows(src, dst, "/src", stat_mtime=False)
    statuses = {r.rel_path: r.dedup_status for r in rows}
    reps = {r.rel_path: r.dedup_representative for r in rows}
    assert statuses == {"a.bin": "kept", "b.bin": "kept"}
    assert reps == {"a.bin": "", "b.bin": ""}


def test_dedup_status_superseded_picks_path_sorted_first():
    """Insta360 sidecar case: LRV_*.bin and VID_*.bin share a hash.
    LRV sorts first → kept; VID is superseded and points at LRV."""
    src = _mf("src", "/src", [
        Entry("VID_017.insv.gyro.bin", "h_gyro", 13_753_440),
        Entry("LRV_017.lrv.gyro.bin", "h_gyro", 13_753_440),
        Entry("VID_001.insv", "h_vid", 877_580_626),  # unique
    ])
    dst = _mf("dst", "/dst", [])
    rows = src_manifest.compute_rows(src, dst, "/src", stat_mtime=False)
    by_path = {r.rel_path: r for r in rows}
    assert by_path["LRV_017.lrv.gyro.bin"].dedup_status == "kept"
    assert by_path["LRV_017.lrv.gyro.bin"].dedup_representative == ""
    assert by_path["VID_017.insv.gyro.bin"].dedup_status == "superseded"
    assert by_path["VID_017.insv.gyro.bin"].dedup_representative == "LRV_017.lrv.gyro.bin"
    assert by_path["VID_001.insv"].dedup_status == "kept"


def test_in_dst_reflects_dst_hash_set():
    src = _mf("src", "/src", [
        Entry("a.bin", "h_a", 10),
        Entry("b.bin", "h_b", 20),
        Entry("c.bin", "h_c", 30),
    ])
    dst = _mf("dst", "/dst", [Entry("a.bin", "h_a", 10), Entry("b.bin", "h_b", 20)])
    rows = src_manifest.compute_rows(src, dst, "/src", stat_mtime=False)
    by_path = {r.rel_path: r.in_dst for r in rows}
    assert by_path == {"a.bin": True, "b.bin": True, "c.bin": False}


def test_compute_rows_sorts_by_rel_path():
    src = _mf("src", "/src", [
        Entry("z.bin", "h_z", 1),
        Entry("a.bin", "h_a", 1),
        Entry("m.bin", "h_m", 1),
    ])
    dst = _mf("dst", "/dst", [])
    rows = src_manifest.compute_rows(src, dst, "/src", stat_mtime=False)
    assert [r.rel_path for r in rows] == ["a.bin", "m.bin", "z.bin"]


def test_src_abs_path_joins_root_with_rel():
    src = _mf("src", "/Volumes/SD/DCIM", [
        Entry("Camera01/x.insv", "h", 1),
    ])
    dst = _mf("dst", "/dst", [])
    rows = src_manifest.compute_rows(src, dst, "/Volumes/SD/DCIM",
                                     stat_mtime=False)
    assert rows[0].src_abs_path == "/Volumes/SD/DCIM/Camera01/x.insv"
    assert rows[0].filename == "x.insv"


# --- write: file emission --------------------------------------------------

def test_write_to_local_dst(tmp_path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "a.bin").write_bytes(b"x" * 10)
    dst_root = tmp_path / "dst"
    dst_root.mkdir()
    fallback = tmp_path / "fb"

    src = _mf("src", str(src_root), [Entry("a.bin", "h_a", 10)])
    dst = _mf("dst", str(dst_root), [])

    out = src_manifest.write(
        src_mf=src, dst_mf=dst,
        src_root=str(src_root), dst_root=str(dst_root),
        fallback_dir=fallback, run_timestamp="2026-05-26_120000Z", v=_v(),
    )
    assert out is not None
    assert out.parent == dst_root
    assert out.name == ".rmig-src-manifest-2026-05-26_120000Z.csv"
    assert out.exists()


def test_write_skips_empty_src(tmp_path):
    src = _mf("src", str(tmp_path), [])
    dst = _mf("dst", str(tmp_path), [])
    out = src_manifest.write(
        src_mf=src, dst_mf=dst,
        src_root=str(tmp_path), dst_root=str(tmp_path),
        fallback_dir=tmp_path / "fb", v=_v(),
    )
    assert out is None


def test_write_csv_columns_and_row_shape(tmp_path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "a.bin").write_bytes(b"x" * 5)
    dst_root = tmp_path / "dst"
    dst_root.mkdir()

    src = _mf("src", str(src_root), [Entry("a.bin", "h_a", 5)])
    dst = _mf("dst", str(dst_root), [Entry("a.bin", "h_a", 5)])

    out = src_manifest.write(
        src_mf=src, dst_mf=dst,
        src_root=str(src_root), dst_root=str(dst_root),
        fallback_dir=tmp_path / "fb", run_timestamp="ts", v=_v(),
    )
    with open(out, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert tuple(header) == src_manifest.COLUMNS
    assert len(rows) == 1
    row = dict(zip(header, rows[0]))
    assert row["filename"] == "a.bin"
    assert row["rel_path"] == "a.bin"
    assert row["src_abs_path"] == str(src_root / "a.bin")
    assert row["size"] == "5"
    assert row["hash_algo"] == "sha256"
    assert row["hash"] == "h_a"
    assert row["dedup_status"] == "kept"
    assert row["dedup_representative"] == ""
    assert row["in_dst"] == "true"
    # mtime is best-effort but the file exists, so it should be populated
    assert row["mtime_utc"].startswith("20")  # ISO date prefix


def test_write_falls_back_for_remote_dst(tmp_path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "a.bin").write_bytes(b"x")
    fb = tmp_path / "fallback"

    src = _mf("src", str(src_root), [Entry("a.bin", "h_a", 1)])
    dst = _mf("dst", "b2:bucket/path", [])

    v = _v()
    out = src_manifest.write(
        src_mf=src, dst_mf=dst,
        src_root=str(src_root), dst_root="b2:bucket/path",
        fallback_dir=fb, run_timestamp="ts", v=v,
    )
    assert out is not None
    assert out.parent == fb
    assert out.exists()


def test_dedup_superseded_count_reflected_in_log(tmp_path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "LRV.bin").write_bytes(b"d")
    (src_root / "VID.bin").write_bytes(b"d")
    dst_root = tmp_path / "dst"
    dst_root.mkdir()

    src = _mf("src", str(src_root), [
        Entry("LRV.bin", "h", 1),
        Entry("VID.bin", "h", 1),
    ])
    dst = _mf("dst", str(dst_root), [])

    out_stream = io.StringIO()
    v = verbose.Verbose(level=verbose.NORMAL, color=False, timestamps=False,
                        stream=out_stream, err_stream=io.StringIO())
    src_manifest.write(
        src_mf=src, dst_mf=dst,
        src_root=str(src_root), dst_root=str(dst_root),
        fallback_dir=tmp_path / "fb", run_timestamp="ts", v=v,
    )
    log = out_stream.getvalue()
    assert "1 superseded" in log


# --- sidecar exclusion -----------------------------------------------------

def test_is_sidecar_matches_src_manifest_csv():
    """The CSV must be excluded by manifest walks — otherwise a subsequent
    dst refresh would hash it as if it were real payload data."""
    assert cache.is_sidecar(".rmig-src-manifest-2026-05-26_120000Z.csv")
    # AppleDouble companion on exFAT/SMB: the OS creates `._<dotfile>`
    # next to dotfiles, so the companion of `.rmig-src-manifest-X.csv`
    # is `._.rmig-src-manifest-X.csv` (double-dot prefix).
    assert cache.is_sidecar("._.rmig-src-manifest-2026-05-26_120000Z.csv")
    # Sanity: regular files aren't accidentally swept up
    assert not cache.is_sidecar("VID_001.insv")
    assert not cache.is_sidecar(".rmig-src-different-thing.txt")
