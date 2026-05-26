"""Emit a CSV manifest of the src view to dst after copy.

`plan_copy()` in ops.py uses `unique_by_hash` to avoid retransmitting
byte-identical duplicates within src — so dst may end up with fewer
file *paths* than src, even though every unique byte stream made it
across. The dst-side inspector then can't answer "what did src look
like at copy time?" without re-mounting src.

This module writes a CSV next to dst's root after each successful
`copy`, recording every src entry with hash, size, dedup status, and
the path that *was* kept on dst when this row was deduped away.

Schema, file naming, default-on rationale: issue #55.
"""
from __future__ import annotations

import csv
import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import manifest as manifest_mod
from . import rclone
from . import verbose as verbose_mod


# Filename: <prefix><run-ts>.csv. The prefix is matched by
# cache.is_sidecar so the CSV doesn't get picked up by a subsequent
# dst refresh and hashed as if it were real payload data.
FILENAME_PREFIX = ".rmig-src-manifest-"
FILENAME_SUFFIX = ".csv"

# CSV column order. Stable; new columns must go at the end so existing
# downstream parsers keep working.
COLUMNS = (
    "filename",              # basename — grep-friendly
    "rel_path",              # path relative to src root — mount-independent identity
    "src_abs_path",          # full path at run time — provenance
    "size",                  # bytes
    "mtime_utc",             # ISO 8601 UTC; empty if stat failed (remote src)
    "hash_algo",
    "hash",                  # lowercase hex
    "dedup_status",          # "kept" | "superseded"
    "dedup_representative",  # rel_path of kept rep when superseded; "" otherwise
    "in_dst",                # "true" | "false" — does dst currently hold this hash
)


def _now_filename_ts() -> str:
    """UTC timestamp for filename: YYYY-MM-DD_HHMMSSZ. Matches the
    same format used by mhl._now_filename_ts so all of a run's emit
    artifacts visually line up."""
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime(
        "%Y-%m-%d_%H%M%SZ"
    )


def _stat_mtime_iso(abs_path: str) -> str:
    """Best-effort ISO 8601 UTC mtime. Empty on stat failure — typically
    means src is a rclone remote backend (no local stat), or the file
    vanished between copy and emit. Either way, the row is still useful
    for hash + dedup_status; mtime is provenance-only."""
    try:
        ts = os.stat(abs_path).st_mtime
    except OSError:
        return ""
    return datetime.datetime.fromtimestamp(
        ts, tz=datetime.timezone.utc
    ).isoformat(timespec="seconds")


def _join(root: str, rel: str) -> str:
    """Join root + rel for both local FS and rclone-remote specs. Mirrors
    ops._join — kept private here to avoid importing from ops (cycle)."""
    if not rel:
        return root
    if root.endswith("/") or root.endswith(":"):
        return f"{root}{rel}"
    return f"{root}/{rel}"


@dataclass(frozen=True)
class _Row:
    filename: str
    rel_path: str
    src_abs_path: str
    size: int
    mtime_utc: str
    hash_algo: str
    hash: str
    dedup_status: str
    dedup_representative: str
    in_dst: bool

    def as_csv_row(self) -> list:
        return [
            self.filename,
            self.rel_path,
            self.src_abs_path,
            self.size,
            self.mtime_utc,
            self.hash_algo,
            self.hash,
            self.dedup_status,
            self.dedup_representative,
            "true" if self.in_dst else "false",
        ]


def compute_rows(
    src_mf: manifest_mod.Manifest,
    dst_mf: manifest_mod.Manifest,
    src_root: str,
    *,
    stat_mtime: bool = True,
) -> List[_Row]:
    """Build CSV rows from manifest objects. Pure function — exposed for
    tests.

    Dedup-representative selection mirrors `Manifest.unique_by_hash`:
    sort by path, keep the first occurrence of each hash. Any later
    entry with the same hash is `superseded` and points at the kept rep.
    """
    repr_by_hash: dict = {}
    for e in sorted(src_mf.entries, key=lambda x: x.path):
        repr_by_hash.setdefault(e.hash, e.path)

    dst_hashes = dst_mf.hash_set()

    rows: List[_Row] = []
    for e in src_mf.entries:
        kept = (repr_by_hash[e.hash] == e.path)
        abs_path = _join(src_root, e.path)
        rows.append(_Row(
            filename=os.path.basename(e.path),
            rel_path=e.path,
            src_abs_path=abs_path,
            size=e.size,
            mtime_utc=_stat_mtime_iso(abs_path) if stat_mtime else "",
            hash_algo=src_mf.algorithm,
            hash=e.hash,
            dedup_status="kept" if kept else "superseded",
            dedup_representative="" if kept else repr_by_hash[e.hash],
            in_dst=(e.hash in dst_hashes),
        ))
    # Sort by rel_path for human review (stable across runs).
    rows.sort(key=lambda r: r.rel_path)
    return rows


def write(
    *,
    src_mf: manifest_mod.Manifest,
    dst_mf: manifest_mod.Manifest,
    src_root: str,
    dst_root: str,
    fallback_dir: Path,
    run_timestamp: Optional[str] = None,
    v: Optional[verbose_mod.Verbose] = None,
) -> Optional[Path]:
    """Write the src manifest CSV. Returns the path written, or None if
    skipped (empty src — nothing to emit).

    Output location:
      - dst is local: ``<dst_root>/<FILENAME_PREFIX><ts>.csv``
      - dst is rclone-remote: ``<fallback_dir>/<FILENAME_PREFIX><ts>.csv``
        with a warn-level log so the operator can stage it manually.
        v1 deliberately does not shell out to ``rclone copyto`` —
        see issue #55 §"Remote dst backends" for the follow-up.
      - dst is local but unwritable (e.g. read-only mount): fall back
        to ``fallback_dir`` with a warn.

    Never overwrites: filename embeds a UTC timestamp. Concurrent runs
    on the same job are prevented by the audit job lock, so the
    one-second resolution of ``run_timestamp`` is sufficient.
    """
    if v is None:
        v = verbose_mod.default()
    if not src_mf.entries:
        v.detail("[src-manifest] skipping (empty src)")
        return None

    rows = compute_rows(src_mf, dst_mf, src_root)
    ts = run_timestamp or _now_filename_ts()
    filename = f"{FILENAME_PREFIX}{ts}{FILENAME_SUFFIX}"

    dst_is_local = rclone.is_local(dst_root)
    if dst_is_local:
        out_path = Path(os.path.expanduser(dst_root)) / filename
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Probe writability without creating the real file yet — a
            # read-only mount would otherwise fail mid-write and leave
            # a half-empty CSV. open(..., 'w') on a RO FS fails fast.
            probe = out_path.with_suffix(out_path.suffix + ".probe")
            try:
                probe.touch()
            finally:
                try:
                    probe.unlink()
                except OSError:
                    # Probe cleanup is best-effort: if .touch() succeeded
                    # the FS is writable, so the real write below will
                    # work; if the probe is gone already (race / another
                    # process) we don't care. Either way, swallowing the
                    # error here is intentional — surfacing it would
                    # mask the real "is dst writable?" signal we came
                    # for, which is the .touch() above.
                    pass
        except OSError as exc:
            v.warn(f"[src-manifest] dst not writable ({exc}); "
                   f"falling back to {fallback_dir}")
            out_path = fallback_dir / filename
    else:
        v.info(f"[src-manifest] dst is rclone-remote ({dst_root!r}); "
               f"writing CSV to {fallback_dir} (stage manually). "
               f"See issue #55.")
        out_path = fallback_dir / filename

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" per Python csv module docs.
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(r.as_csv_row())

    superseded = sum(1 for r in rows if r.dedup_status == "superseded")
    v.info(
        f"[src-manifest] wrote {len(rows)} rows "
        f"({superseded} superseded by dedup) → {out_path}"
    )
    return out_path
