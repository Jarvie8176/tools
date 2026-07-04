"""Runtime configuration — a local JSON file, the persisted source for UI-tunable knobs.

Precedence: ``DEFAULTS`` <- config file (``~/.claude/cc-monitor-config.json``, UI/API-managed)
<- env var (an ops escape hatch, highest). Deploy-level knobs (bind ``HOST``/``PORT``, the refresh
cadence, filesystem paths) are NOT here — they stay in ``install/.env`` + ``paths.py``; you can't
rebind a socket or move a mount from a dashboard.

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
    "busy_idle_gap":     (12, 1, 3600),     # s of transcript silence before mtime heuristic -> idle
    "active_gap":        (900, 1, 86400),   # s before an alive session is "idle" vs "active" (M-B)
    "ctx_warn_pct":      (50, 0, 100),       # context-usage colour: amber above this
    "ctx_crit_pct":      (80, 0, 100),       # context-usage colour: red above this
    "title_trunc_text":  (22, 4, 512),
    "prompt_trunc_text": (40, 4, 512),
    "title_trunc_html":  (48, 4, 512),
    "prompt_trunc_html": (70, 4, 512),
    "redact_default":    (False, None, None),  # on -> server masks prompt+title before output (privacy.py)
}
DEFAULTS: dict = {k: v[0] for k, v in SCHEMA.items()}

# ops escape hatch: env var wins over the file for these keys.
_ENV = {"busy_idle_gap": "CC_MONITOR_BUSY_IDLE_GAP"}

# Cache as a SINGLE tuple (key, value) rebound atomically — NOT a two-field dict. A dict update
# (`_cache["key"], _cache["value"] = ...`) is two separate stores, so a concurrent reader could
# observe the new key paired with the old/None value (a torn read → stale config, or `dict(None)`
# on cold start). A lone tuple rebind is one atomic reference swap: a reader sees the old pair or
# the new pair, never a mix. Matters under a free-threaded build and at cold-start first-request.
_cache: tuple | None = None  # (key, merged-config); None = empty / invalidated


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
    global _cache
    path = path or paths.CONFIG_FILE
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    key = (path, mtime)
    cached = _cache  # single atomic read of the (key, value) pair — cannot tear
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
    _cache = (key, cfg)  # single atomic rebind
    return dict(cfg)


def save(partial: dict, path: str | None = None) -> dict:
    """Merge ``partial`` into the config file (schema-gated, atomic write); return new effective."""
    global _cache
    path = path or paths.CONFIG_FILE
    merged = _read_raw(path)
    for k, v in (partial or {}).items():
        if k in SCHEMA:  # ignore unknown keys — never let a caller write arbitrary content
            merged[k] = _coerce(k, v)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cc-monitor-config.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(merged, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)  # atomic — a concurrent reader never sees a half-written file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _cache = None  # invalidate
    return load(path)
