"""Local title override.

RC env-spawned sessions (the GUI's set) have no local ``custom-title`` — the real title lives
cloud-side only. This provides a hand-maintained local map so the dashboard can show a human
title without the cloud API. Keyed by ``sessionId`` (uuid) OR ``bridgeSessionId`` (session_xxx).

Title resolution precedence (applied in collect): override -> custom-title -> '' (cloud-side).
"""
from __future__ import annotations

import json
import os
import tempfile

from . import paths


def load(path: str | None = None) -> dict:
    """Return the override map, or {} on missing/corrupt file (graceful degradation)."""
    path = path or paths.TITLES_FILE
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(key: str, title: str, path: str | None = None) -> dict:
    """Set (or clear) one override, atomically; return the new map.

    ``title`` empty/whitespace clears the key (removes the override so resolution falls back to
    custom-title / cloud-side). Starts from the on-disk map so a concurrent hand-edit of *other*
    keys survives; a corrupt file degrades to an empty base (same as ``load``) rather than crashing.
    Written to a temp file + ``os.replace`` so a reader never sees a half-written map.
    """
    path = path or paths.TITLES_FILE
    data = load(path)
    title = (title or "").strip()
    if title:
        data[key] = title
    else:
        data.pop(key, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cc-monitor-titles.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)  # atomic — a concurrent reader never sees a partial file
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return data


def resolve(overrides: dict, session_id: str, bridge_id: str | None) -> str:
    """Override title for a session, by sessionId or bridgeSessionId, else ''.

    Values are coerced to ``str`` — the file is hand-maintained, and a non-string value
    (e.g. a number from a missing-quotes typo) must not crash rendering downstream.
    """
    for key in (session_id, bridge_id):
        if key and key in overrides:
            val = overrides[key]
            return str(val) if val is not None else ""
    return ""
