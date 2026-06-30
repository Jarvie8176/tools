"""Seed the local hash cache from externally-computed fixity (`rmig import`).

`rmig-hash` is the only way hashes normally enter the cache — rmig computes
them itself. But fixity is often produced *outside* rmig: `xxhsum -H128`,
`rclone hashsum`, an offload ledger, or the MHL/CSV that `export-mhl` wrote on
another host. This module reads such a CSV and `INSERT OR REPLACE`s it into the
side's `hash_cache` table, the same store `rmig-hash` fills.

It is the read-direction pair of the exporter: `export` (MHL/CSV) carries
fixity *out*; `import` (CSV) brings it back *in* — so you can hash at the
source, carry the CSV, and verify at the destination without re-reading TBs.

Scope: local sides only. A remote side's hashes live in
`state.db.remote_hash_cache` (populated live by `rmig-hash`), a different store
with no `source`/provenance column — importing there is out of scope here.

CSV contract (header-driven, column order irrelevant):
    path,algorithm,hash,size,mtime,source
  - path       (required) relative to the side's root, or absolute under it.
  - hash       (required) hex digest; stored lowercased.
  - algorithm  (optional) must equal the job's negotiated algo (reject drift).
  - size,mtime (optional) integer bytes / epoch seconds. Required by the cache
                schema (NOT NULL); supply them, or pass --stat to read them
                off disk. mtime is what rmig trusts for cache-staleness, so an
                imported row whose mtime ≠ the file's is treated as stale and
                re-hashed later (safe, never wrong).
  - source     (optional) provenance string; falls back to --source, then
                'csv-import'.
"""
from __future__ import annotations

import csv
import io
import os
import posixpath
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import cache as cache_mod
from . import rclone
from . import state as state_mod
from . import verbose as verbose_mod
from .config import Config, Job
from .hashing import normalize as normalize_algo

# Header columns we understand. Unknown columns are ignored (forward-compat).
_REQUIRED_COLS = ("path", "hash")
_KNOWN_COLS = ("path", "algorithm", "hash", "size", "mtime", "source")


class ImportError_(ValueError):
    """A user-correctable problem with the CSV or invocation (→ exit 2)."""


def _resolve_local_cache_db(cfg: Config, job: Job, side: str) -> Tuple[Path, Path]:
    """Resolve (db_path, root_path) for a *local* side, with create semantics
    matching the refresh/copy path (writes the .rmig-dataset marker / migrates
    a legacy path-keyed db when out-of-root caching is configured). Mirrors
    manifest._refresh_local so import and hash share the exact same db."""
    root = job.src if side == "src" else job.dst
    if not rclone.is_local(root):
        raise ImportError_(
            f"--side {side} root '{root}' is remote. `rmig import` seeds the "
            f"local hash cache; remote-side hashes live in "
            f"state.db.remote_hash_cache (populated by `rmig-hash`)."
        )
    root_path = Path(os.path.expanduser(root))
    if not root_path.exists():
        raise ImportError_(f"local root does not exist: {root_path}")
    state_dir = cfg.state_dir_for(job)
    fallback = state_dir / "local-cache"
    if job.resolved_local_cache_in_root(cfg.defaults):
        db_path = cache_mod.cache_path_for_root(root_path, fallback_dir=fallback)
    else:
        db_path, _ = cache_mod.resolve_fallback_db(root_path, fallback, create=True)
    return db_path, root_path


def _normalize_csv_path(raw: str, root_path: Path) -> str:
    """Return a root-relative POSIX path. Absolute paths must live under root."""
    raw = raw.strip()
    p = Path(raw)
    if p.is_absolute():
        rp = Path(os.path.normpath(os.path.expanduser(raw)))
        try:
            rel = rp.relative_to(root_path)
        except ValueError:
            raise ImportError_(
                f"absolute path '{raw}' is not under the side root {root_path}"
            )
        return rel.as_posix()
    # Relative — normalize separators / '.' segments but keep it relative.
    norm = posixpath.normpath(raw.replace(os.sep, "/"))
    if norm == "." or norm.startswith("..") or posixpath.isabs(norm):
        raise ImportError_(f"path '{raw}' escapes the side root")
    return norm


def parse_csv(text: str) -> List[dict]:
    """Parse CSV text into a list of lowercased-key dict rows. Validates the
    header carries the required columns. Raises ImportError_ on bad header."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ImportError_("empty CSV (no header row)")
    # Normalize header names (strip + lowercase + drop a UTF-8 BOM on col 0).
    fields = [(f or "").strip().lstrip("﻿").lower() for f in reader.fieldnames]
    missing = [c for c in _REQUIRED_COLS if c not in fields]
    if missing:
        raise ImportError_(
            f"CSV header missing required column(s): {', '.join(missing)} "
            f"(got: {', '.join(fields)})"
        )
    rows: List[dict] = []
    for raw in reader:
        # Re-key with the normalized header names, in row order.
        row = {}
        for orig, norm in zip(reader.fieldnames, fields):
            if norm in _KNOWN_COLS:
                row[norm] = raw.get(orig)
        rows.append(row)
    return rows


def _build_entry(
    row: dict, expected_algo: str, root_path: Path, *,
    stat: bool, source_default: str, lineno: int,
) -> cache_mod.ImportEntry:
    """Turn one CSV row into a validated ImportEntry, or raise ImportError_
    with the line number for any rejection."""
    def fail(msg: str):
        raise ImportError_(f"row {lineno}: {msg}")

    raw_path = (row.get("path") or "").strip()
    if not raw_path:
        fail("empty path")
    rel = _normalize_csv_path(raw_path, root_path)

    hsh = (row.get("hash") or "").strip().lower()
    if not hsh:
        fail("empty hash")

    row_algo = (row.get("algorithm") or "").strip()
    if row_algo and normalize_algo(row_algo) != expected_algo:
        fail(
            f"algorithm '{row_algo}' != job algorithm '{expected_algo}' "
            f"(silent algo drift refused)"
        )

    size_raw = (row.get("size") or "").strip()
    mtime_raw = (row.get("mtime") or "").strip()
    size: Optional[int] = None
    mtime: Optional[float] = None
    if size_raw:
        try:
            size = int(size_raw)
        except ValueError:
            fail(f"size '{size_raw}' is not an integer")
    if mtime_raw:
        try:
            mtime = float(mtime_raw)
        except ValueError:
            fail(f"mtime '{mtime_raw}' is not a number")

    if size is None or mtime is None:
        if not stat:
            fail("missing size/mtime — supply both columns or pass --stat")
        try:
            st = (root_path / rel).stat()
        except OSError as e:
            fail(f"--stat could not read {rel}: {e}")
        if size is None:
            size = st.st_size
        if mtime is None:
            mtime = st.st_mtime

    source = (row.get("source") or "").strip() or source_default
    return cache_mod.ImportEntry(
        path=rel, algorithm=expected_algo, hash=hsh,
        size=size, mtime=mtime, source=source,
    )


def _common_prefix(rels: List[str]) -> str:
    """Deepest directory all imported paths sit under (the prune subtree).
    Empty string means they span the whole root — prune would clear it all."""
    dirs = [posixpath.dirname(r) for r in rels]
    if not dirs or "" in dirs:
        return ""
    if len(set(dirs)) == 1:
        return dirs[0]
    try:
        return posixpath.commonpath(dirs)
    except ValueError:
        return ""


def do_import(
    cfg: Config,
    job: Job,
    *,
    side: str,
    csv_path: str,
    expected_algo: str,
    algorithm_override: Optional[str] = None,
    stat: bool = False,
    prune: bool = False,
    source_default: str = "csv-import",
    dry_run: bool = False,
    v: Optional[verbose_mod.Verbose] = None,
) -> Tuple[int, int]:
    """Import `csv_path` into `side`'s local hash cache.

    Validation is all-or-nothing: any bad row aborts before a single write.
    Returns (inserted, pruned) row counts. Raises ImportError_ on user error.
    """
    if v is None:
        v = verbose_mod.default()

    if algorithm_override:
        ovr = normalize_algo(algorithm_override)
        if ovr != expected_algo:
            raise ImportError_(
                f"--algorithm '{algorithm_override}' != job's configured "
                f"algorithm '{expected_algo}' (silent algo drift refused)"
            )

    db_path, root_path = _resolve_local_cache_db(cfg, job, side)

    csv_file = Path(os.path.expanduser(csv_path))
    if not csv_file.is_file():
        raise ImportError_(f"CSV not found: {csv_file}")
    rows = parse_csv(csv_file.read_text(encoding="utf-8-sig"))
    if not rows:
        v.warn(f"[import] {csv_file} has a header but no data rows; nothing to do")
        return (0, 0)

    # Validate + build every entry first (DictReader row 1 is CSV line 2).
    entries = [
        _build_entry(row, expected_algo, root_path,
                     stat=stat, source_default=source_default, lineno=i + 2)
        for i, row in enumerate(rows)
    ]

    prefix = _common_prefix([e.path for e in entries]) if prune else ""

    v.info(
        f"[import] side={side} algo={expected_algo} rows={len(entries)} "
        f"→ {db_path}"
    )
    if dry_run:
        if prune:
            label = f"'{prefix}/'" if prefix else "the ENTIRE side cache (no common prefix!)"
            v.info(f"[import] (dry-run) --prune would clear {label} before insert")
        v.info(f"[import] (dry-run) would INSERT OR REPLACE {len(entries)} rows; "
               f"no changes written")
        return (0, 0)

    conn = cache_mod.open_db(db_path)
    try:
        pruned = 0
        if prune:
            pruned = cache_mod.count_under_prefix(conn, prefix, expected_algo)
            if not prefix:
                v.warn(
                    f"[import] --prune: imported paths share no common prefix; "
                    f"clearing the ENTIRE {expected_algo} cache for this side "
                    f"({pruned} rows) before insert"
                )
            else:
                v.info(f"[import] --prune: clearing {pruned} existing rows under "
                       f"'{prefix}/' (subtree refresh)")
            cache_mod.delete_under_prefix(conn, prefix, expected_algo)
        inserted = cache_mod.import_many(conn, entries, refreshed=time.time())
        cache_mod.meta_set(conn, "last_import_ts",
                           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        v.ok(f"[import] {inserted} rows written"
             + (f", {pruned} pruned" if prune else ""))
    finally:
        conn.close()

    # Record the algorithm in state.db so the query layer (file-status /
    # find-by-hash) can find these rows without a prior rmig-hash run — an
    # import-only workflow (hash at source, import at dest) is otherwise
    # invisible to it. Mirrors what rmig-hash/check write.
    state_conn = state_mod.open_db(cfg.state_dir_for(job))
    try:
        state_mod.meta_set(state_conn, "hash_algorithm", expected_algo)
    finally:
        state_conn.close()
    return (inserted, pruned)
