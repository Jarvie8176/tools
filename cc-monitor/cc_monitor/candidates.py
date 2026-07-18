"""Auto-detected window candidates — a MONITOR-written map keyed by bare model id.

When the resolver decides a session's window from real evidence (an explicit ceiling, a ``[1m]``
env marker, or an observed peak that proves the larger window), the monitor records that
``model -> window`` here as a *candidate*. A candidate has one job: fill the display for a model
whose window is otherwise locally unknowable (env unreadable + low usage), so a freshly-started
low-context session on a known model shows the right capacity instead of a bare ``?``.

Kept in a SEPARATE file from the operator's own config (:mod:`.models`) so:
  * the automatic write never touches (or races) a hand-maintained file, and
  * a candidate is ALWAYS an evidence-derived snapshot — it is written ONLY from a real detection,
    never from a manual override or a prior candidate, so it can never launder an operator's
    temporary override back in as if it were detected.

A candidate NEVER overrides live evidence — it sits at the bottom of the precedence chain and only
supplies a value when nothing authoritative is available (see :func:`.window.apply_model_window`).
"""
from __future__ import annotations

import json
import os
import tempfile

from . import paths


def load(path: str | None = None) -> dict:
    """Return the candidate map ``{model: window}``, or {} on missing/corrupt file."""
    path = path or paths.CANDIDATES_FILE
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(cands: dict, model: str) -> int | None:
    """Candidate window (>0) for ``model``, or None. Non-int/≤0 is treated as absent."""
    if not isinstance(cands, dict):
        return None
    try:
        w = int(cands.get(model))
    except (TypeError, ValueError):
        return None
    return w if w > 0 else None


def save(model: str, window: int, path: str | None = None) -> dict:
    """Record one model's detected window, atomically; return the new map.

    Caller MUST gate this on a real-evidence detection (never a manual override / prior
    candidate) — this function does not re-check provenance, it only persists. Starts from the
    on-disk map so a concurrent entry for another model survives; temp+rename so a reader never
    sees a partial file.
    """
    path = path or paths.CANDIDATES_FILE
    data = load(path)
    try:
        w = int(window)
    except (TypeError, ValueError):
        return data
    if w <= 0:
        return data
    data[model] = w
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cc-monitor-cand.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)  # atomic — a concurrent reader never sees a partial file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return data
