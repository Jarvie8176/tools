"""Runtime configuration — a local JSON file, the persisted source for UI-tunable knobs.

Precedence: ``DEFAULTS`` <- config file (``paths.CONFIG_FILE``, UI/API-managed) <- env var (an ops
escape hatch, highest). Deploy-level knobs (bind ``HOST``/``PORT``, the refresh cadence, the
upstream Prometheus URL) are NOT here — they stay in ``install/.env`` + ``paths.py``; you can't
rebind a socket or repoint the upstream from a dashboard.

The file is re-read only when its mtime changes, so a UI/API edit takes effect on the next
refresh without a restart, but a steady refresh loop doesn't re-parse it every time. Unknown keys
and out-of-range / mistyped values fall back to the default — the file is hand- or UI-written and
must never crash a render or let one field poison the rest.
"""
from __future__ import annotations

import json
import os
import tempfile

from . import paths

# key -> (default, min, max). A None min marks a bool knob; everything else is a bounded int.
SCHEMA: dict = {
    "ctx_warn_pct":  (50, 0, 100),      # per-session context-usage colour: amber above this
    "ctx_crit_pct":  (80, 0, 100),      # per-session context-usage colour: red above this
    "vram_warn_pct": (85, 0, 100),      # host VRAM colour: amber above this (Metal 75% cap context)
    "tps_floor":     (15, 0, 100000),   # tok/s below this = GPU dropped offload (G3); UI flags red
}
DEFAULTS: dict = {k: v[0] for k, v in SCHEMA.items()}

# ops escape hatch: env var wins over the file for these keys. (None mapped for now.)
_ENV: dict = {}

# Per-invocation CLI overrides (e.g. `--redact` / `--no-redact`) — the HIGHEST-precedence layer,
# applied on top of file+env in load(). Set once at process start from the CLI; NEVER persisted to
# the config file (save() only touches file-backed keys). A single dict, replaced wholesale so a
# concurrent reader sees the old map or the new one, never a partial update.
_overrides: dict = {}


def set_overrides(**kw) -> None:
    """Install per-invocation overrides (drop None-valued keys so an unset flag is a no-op)."""
    global _overrides
    _overrides = {k: v for k, v in kw.items() if v is not None and k in SCHEMA}
    _cache[0] = None  # invalidate: a cached effective config predates these overrides


# Cache as a one-slot holder whose element is a SINGLE (key, value) tuple — NOT a two-field dict.
# A dict update (`_cache["key"], _cache["value"] = ...`) is two separate stores, so a concurrent
# reader could observe the new key paired with the old/None value (a torn read → stale config, or
# `dict(None)` on cold start). Assigning `_cache[0] = (key, cfg)` is one subscript store (atomic
# under the GIL, and list ops are individually atomic under free-threaded 3.14t too): a reader sees
# the old pair or the new pair, never a mix. The holder also avoids a `global` rebind in save().
_cache: list = [None]  # _cache[0] = (key, merged-config); None = empty / invalidated


def _coerce(key: str, raw):
    """Coerce ``raw`` to the schema type for ``key``, clamped to range; default on any failure."""
    default, lo, hi = SCHEMA[key]
    if isinstance(default, bool):  # bool BEFORE int (bool is a subclass of int)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw) if isinstance(raw, (int, float)) else default
    try:
        return max(lo, min(hi, int(raw)))
    except (ValueError, TypeError):
        return default


def _read_raw(path: str) -> dict:
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(path: str | None = None) -> dict:
    """Return the effective config (defaults <- file <- env), re-parsing only on mtime change."""
    path = path or paths.CONFIG_FILE
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime)
    cached = _cache[0]  # single atomic read of the (key, value) pair — cannot tear
    if cached is not None and cached[0] == key:
        return dict(cached[1])  # copy — callers must not mutate the cache
    cfg = dict(DEFAULTS)
    raw = _read_raw(path)
    for k in SCHEMA:
        if k in raw:
            cfg[k] = _coerce(k, raw[k])
    for k, env in _ENV.items():  # env overrides the file (ops hard override)
        if os.environ.get(env) is not None:
            cfg[k] = _coerce(k, os.environ[env])
    for k, v in _overrides.items():  # per-invocation CLI override — highest precedence, not persisted
        cfg[k] = _coerce(k, v)
    _cache[0] = (key, cfg)  # single atomic store
    return dict(cfg)


def save(partial: dict, path: str | None = None) -> dict:
    """Merge ``partial`` into the config file (schema-gated, atomic write); return new effective."""
    path = path or paths.CONFIG_FILE
    # Start from the on-disk config but drop any key no longer in SCHEMA (e.g. a removed knob), so a
    # save cleans stale keys off disk rather than persisting them forever.
    merged = {k: v for k, v in _read_raw(path).items() if k in SCHEMA}
    for k, v in (partial or {}).items():
        if k in SCHEMA:  # ignore unknown keys — never let a caller write arbitrary content
            merged[k] = _coerce(k, v)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".llm-pm-config.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(merged, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)  # atomic — a concurrent reader never sees a half-written file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _cache[0] = None  # invalidate (guards a coarse-mtime FS where save+load share an mtime tick)
    return load(path)
