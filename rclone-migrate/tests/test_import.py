"""`rmig import` — external-fixity CSV → hash_cache (Jarvie8176/tools#73)."""
import sqlite3
from pathlib import Path

import pytest

from rclone_migrate import cache as cache_mod
from rclone_migrate import config as config_mod
from rclone_migrate import importer


# --- config fixture (no rclone needed: do_import takes expected_algo) ---------

def _write_config(path: Path, src: Path, dst: Path, state_dir: Path) -> None:
    path.write_text(
        "[defaults]\n"
        f"state_dir = '{state_dir}'\n"
        "local_cache_in_root = true\n"
        "[[jobs]]\n"
        "name = 't'\n"
        f"src = '{src}'\n"
        f"dst = '{dst}'\n"
    )


def _job(tmp_path: Path):
    src = tmp_path / "src"; dst = tmp_path / "dst"; sd = tmp_path / "state"
    for d in (src, dst, sd):
        d.mkdir()
    cfg_path = tmp_path / "c.toml"
    _write_config(cfg_path, src, dst, sd)
    cfg = config_mod.load(cfg_path)
    return cfg, cfg.get_job("t"), src, dst


def _csv(tmp_path: Path, text: str) -> str:
    p = tmp_path / "fixity.csv"
    p.write_text(text)
    return str(p)


# --- cache layer --------------------------------------------------------------

def test_source_column_migrated_onto_legacy_db(tmp_path: Path):
    """A db created before `source` existed gains the column on open_db."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE hash_cache (path TEXT NOT NULL, algorithm TEXT NOT NULL, "
        "hash TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL, "
        "refreshed REAL NOT NULL, PRIMARY KEY (path, algorithm))"
    )
    conn.commit(); conn.close()

    conn = cache_mod.open_db(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(hash_cache)")}
    assert "source" in cols
    conn.close()


def test_import_many_persists_source(tmp_path: Path):
    conn = cache_mod.open_db(tmp_path / "c.db")
    e = cache_mod.ImportEntry("a/b.jpg", "xxh128", "deadbeef", 10, 100.0, "xxhsum")
    assert cache_mod.import_many(conn, [e], refreshed=200.0) == 1
    row = conn.execute(
        "SELECT hash, source FROM hash_cache WHERE path = 'a/b.jpg'"
    ).fetchone()
    assert row == ("deadbeef", "xxhsum")
    conn.close()


def test_prune_escapes_underscore(tmp_path: Path):
    """A literal '_' in a prefix must not match arbitrary chars (over-delete)."""
    conn = cache_mod.open_db(tmp_path / "c.db")
    rows = [
        cache_mod.ImportEntry("raw_a/x.jpg", "md5", "h1", 1, 1.0, "s"),
        cache_mod.ImportEntry("rawXa/y.jpg", "md5", "h2", 1, 1.0, "s"),  # decoy
    ]
    cache_mod.import_many(conn, rows, refreshed=1.0)
    assert cache_mod.count_under_prefix(conn, "raw_a", "md5") == 1
    deleted = cache_mod.delete_under_prefix(conn, "raw_a", "md5")
    assert deleted == 1
    remaining = {r[0] for r in conn.execute("SELECT path FROM hash_cache")}
    assert remaining == {"rawXa/y.jpg"}
    conn.close()


def test_prune_is_per_algorithm(tmp_path: Path):
    conn = cache_mod.open_db(tmp_path / "c.db")
    cache_mod.import_many(conn, [
        cache_mod.ImportEntry("d/f", "md5", "h1", 1, 1.0, "s"),
        cache_mod.ImportEntry("d/f", "xxh128", "h2", 1, 1.0, "s"),
    ], refreshed=1.0)
    cache_mod.delete_under_prefix(conn, "d", "md5")
    algos = {r[0] for r in conn.execute("SELECT algorithm FROM hash_cache")}
    assert algos == {"xxh128"}
    conn.close()


# --- CSV parsing --------------------------------------------------------------

def test_parse_csv_order_independent_and_bom():
    text = "﻿hash,source,path\nABC123,xxhsum,a/b.jpg\n"
    rows = importer.parse_csv(text)
    assert rows == [{"hash": "ABC123", "source": "xxhsum", "path": "a/b.jpg"}]


def test_parse_csv_missing_required_column():
    with pytest.raises(importer.ImportError_, match="missing required column"):
        importer.parse_csv("path,size\na/b.jpg,10\n")


# --- path normalization -------------------------------------------------------

def test_normalize_relative_kept(tmp_path: Path):
    assert importer._normalize_csv_path("a/./b.jpg", tmp_path) == "a/b.jpg"


def test_normalize_absolute_under_root(tmp_path: Path):
    abs_p = str(tmp_path / "a" / "b.jpg")
    assert importer._normalize_csv_path(abs_p, tmp_path) == "a/b.jpg"


def test_normalize_absolute_outside_root_rejected(tmp_path: Path):
    with pytest.raises(importer.ImportError_, match="not under the side root"):
        importer._normalize_csv_path("/some/other/x.jpg", tmp_path)


def test_normalize_escape_rejected(tmp_path: Path):
    with pytest.raises(importer.ImportError_, match="escapes"):
        importer._normalize_csv_path("../escape.jpg", tmp_path)


def test_common_prefix():
    assert importer._common_prefix(["a/b/x", "a/b/y"]) == "a/b"
    assert importer._common_prefix(["a/b/x", "a/c/y"]) == "a"
    assert importer._common_prefix(["top.jpg", "a/b"]) == ""   # spans root


# --- do_import end-to-end (no rclone) -----------------------------------------

def test_do_import_basic(tmp_path: Path):
    cfg, job, src, _dst = _job(tmp_path)
    csv = _csv(tmp_path,
               "path,algorithm,hash,size,mtime\n"
               "a/b.jpg,md5,DEADBEEF,10,100.0\n")
    inserted, pruned = importer.do_import(
        cfg, job, side="src", csv_path=csv, expected_algo="md5")
    assert (inserted, pruned) == (1, 0)
    conn = cache_mod.open_db(src / cache_mod.CACHE_FILENAME)
    row = conn.execute("SELECT hash, source FROM hash_cache").fetchone()
    assert row == ("deadbeef", "csv-import")   # hash lowercased, default source
    conn.close()


def test_do_import_records_algorithm_in_state(tmp_path: Path):
    """Import-only workflow must leave hash_algorithm in state.db so the
    query layer (file-status) can find the rows without a prior rmig-hash."""
    from rclone_migrate import state as state_mod
    cfg, job, _src, _dst = _job(tmp_path)
    csv = _csv(tmp_path, "path,hash,size,mtime\na.jpg,h,1,1\n")
    importer.do_import(cfg, job, side="src", csv_path=csv, expected_algo="md5")
    conn = state_mod.open_db(cfg.state_dir_for(job))
    assert state_mod.meta_get(conn, "hash_algorithm") == "md5"
    conn.close()


def test_do_import_algo_drift_rejected(tmp_path: Path):
    cfg, job, _src, _dst = _job(tmp_path)
    csv = _csv(tmp_path, "path,algorithm,hash,size,mtime\na,sha1,h,1,1\n")
    with pytest.raises(importer.ImportError_, match="drift"):
        importer.do_import(cfg, job, side="src", csv_path=csv,
                           expected_algo="md5")


def test_do_import_override_drift_rejected(tmp_path: Path):
    cfg, job, _src, _dst = _job(tmp_path)
    csv = _csv(tmp_path, "path,hash,size,mtime\na,h,1,1\n")
    with pytest.raises(importer.ImportError_, match="drift"):
        importer.do_import(cfg, job, side="src", csv_path=csv,
                           expected_algo="md5", algorithm_override="sha1")


def test_do_import_missing_stat_rejected(tmp_path: Path):
    cfg, job, _src, _dst = _job(tmp_path)
    csv = _csv(tmp_path, "path,hash\na/b.jpg,h\n")
    with pytest.raises(importer.ImportError_, match="--stat"):
        importer.do_import(cfg, job, side="src", csv_path=csv,
                           expected_algo="md5")


def test_do_import_stat_fills_size_mtime(tmp_path: Path):
    cfg, job, src, _dst = _job(tmp_path)
    (src / "a").mkdir()
    (src / "a" / "b.jpg").write_bytes(b"hello")
    csv = _csv(tmp_path, "path,hash\na/b.jpg,abc\n")
    inserted, _ = importer.do_import(
        cfg, job, side="src", csv_path=csv, expected_algo="md5", stat=True)
    assert inserted == 1
    conn = cache_mod.open_db(src / cache_mod.CACHE_FILENAME)
    size = conn.execute("SELECT size FROM hash_cache").fetchone()[0]
    assert size == 5
    conn.close()


def test_do_import_atomic_on_bad_row(tmp_path: Path):
    """One bad row aborts the whole import — nothing written."""
    cfg, job, src, _dst = _job(tmp_path)
    csv = _csv(tmp_path,
               "path,hash,size,mtime\n"
               "good.jpg,h1,1,1\n"
               "bad.jpg,h2,notanint,1\n")
    with pytest.raises(importer.ImportError_, match="row 3"):
        importer.do_import(cfg, job, side="src", csv_path=csv,
                           expected_algo="md5")
    assert not (src / cache_mod.CACHE_FILENAME).exists()


def test_do_import_prune_drops_orphans(tmp_path: Path):
    cfg, job, src, _dst = _job(tmp_path)
    # Pre-seed an orphan (a renamed-away path) under the same subtree.
    conn = cache_mod.open_db(src / cache_mod.CACHE_FILENAME)
    cache_mod.import_many(conn, [
        cache_mod.ImportEntry("raw/OLDNAME.jpg", "md5", "old", 1, 1.0, "s"),
    ], refreshed=1.0)
    conn.close()
    csv = _csv(tmp_path,
               "path,algorithm,hash,size,mtime\n"
               "raw/newname.jpg,md5,new,2,2.0\n")
    inserted, pruned = importer.do_import(
        cfg, job, side="src", csv_path=csv, expected_algo="md5", prune=True)
    assert (inserted, pruned) == (1, 1)
    conn = cache_mod.open_db(src / cache_mod.CACHE_FILENAME)
    paths = {r[0] for r in conn.execute("SELECT path FROM hash_cache")}
    assert paths == {"raw/newname.jpg"}   # orphan gone
    conn.close()


def test_do_import_dry_run_writes_nothing(tmp_path: Path):
    cfg, job, src, _dst = _job(tmp_path)
    csv = _csv(tmp_path, "path,hash,size,mtime\na.jpg,h,1,1\n")
    inserted, pruned = importer.do_import(
        cfg, job, side="src", csv_path=csv, expected_algo="md5", dry_run=True)
    assert (inserted, pruned) == (0, 0)
    assert not (src / cache_mod.CACHE_FILENAME).exists()


def test_do_import_remote_side_rejected(tmp_path: Path):
    cfg_path = tmp_path / "c.toml"
    sd = tmp_path / "state"; sd.mkdir()
    cfg_path.write_text(
        "[defaults]\n"
        f"state_dir = '{sd}'\n"
        "[[jobs]]\n"
        "name = 't'\n"
        f"src = '{tmp_path / 'src'}'\n"
        "dst = 'remote:bucket/path'\n"
    )
    (tmp_path / "src").mkdir()
    cfg = config_mod.load(cfg_path)
    job = cfg.get_job("t")
    csv = _csv(tmp_path, "path,hash,size,mtime\na,h,1,1\n")
    with pytest.raises(importer.ImportError_, match="remote"):
        importer.do_import(cfg, job, side="dst", csv_path=csv,
                           expected_algo="md5")
