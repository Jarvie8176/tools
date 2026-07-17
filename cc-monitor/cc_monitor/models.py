"""Per-model operator config — a hand/UI-maintained local map keyed by bare model id.

Two operator-authored fields per model:
  * ``alias``  — a human label shown in place of the verbose model id (display only; never
                 changes the model key used for joins, metrics labels, or window lookup).
  * ``window`` — a manual context-window override. When set (>0) it is the AUTHORITATIVE window
                 for every session on that model — highest precedence, above any auto-detected
                 signal. Empty/unset falls back to the evidence chain (see :mod:`.window`).

Keyed by the BARE model id (e.g. ``claude-opus-4-8``, no ``[1m]`` suffix) — the same string the
transcript reports and every session on that model shares, so one entry covers all its sessions.

This file is OPERATOR-owned. The auto-detected window candidate lives in a SEPARATE file
(:mod:`.candidates`) written by the monitor, so an automatic write can never clobber a hand edit.
"""
from __future__ import annotations

import json
import os
import tempfile

from . import paths

_UNSET = object()  # sentinel: "field not supplied" — distinct from "supplied empty" (which clears)
_MAX_ALIAS = 64    # aliases are short labels; cap a hand-edited/garbage value defensively


def load(path: str | None = None) -> dict:
    """Return the model-config map, or {} on missing/corrupt file (graceful degradation)."""
    path = path or paths.MODELS_FILE
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cc-monitor-models.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)  # atomic — a concurrent reader never sees a partial file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(model: str, *, alias=_UNSET, window=_UNSET, path: str | None = None) -> dict:
    """Update one model's config, atomically; return the new map.

    Only the fields explicitly passed are touched (``_UNSET`` leaves a field as-is). An empty
    ``alias`` or a non-positive/None ``window`` CLEARS that field. A model whose entry ends up
    empty is dropped entirely (so a clear leaves no residue). Starts from the on-disk map so a
    concurrent hand-edit of OTHER models survives; a corrupt file degrades to empty (like load).
    """
    path = path or paths.MODELS_FILE
    data = load(path)
    entry = dict(data.get(model) or {}) if isinstance(data.get(model), dict) else {}
    if alias is not _UNSET:
        a = (alias or "").strip()[:_MAX_ALIAS]
        if a:
            entry["alias"] = a
        else:
            entry.pop("alias", None)
    if window is not _UNSET:
        try:
            w = int(window)
        except (TypeError, ValueError):
            w = 0
        if w > 0:
            entry["window"] = w
        else:
            entry.pop("window", None)
    if entry:
        data[model] = entry
    else:
        data.pop(model, None)
    _write(data, path)
    return data


def alias_of(models: dict, model: str) -> str:
    """Operator alias for ``model``, or '' — coerced to str (hand-maintained file)."""
    entry = models.get(model) if isinstance(models, dict) else None
    if isinstance(entry, dict) and entry.get("alias"):
        return str(entry["alias"])
    return ""


def override_of(models: dict, model: str) -> int | None:
    """Manual window override (>0) for ``model``, or None. Non-int/≤0 is treated as absent."""
    entry = models.get(model) if isinstance(models, dict) else None
    if isinstance(entry, dict):
        try:
            w = int(entry.get("window"))
        except (TypeError, ValueError):
            return None
        if w > 0:
            return w
    return None
