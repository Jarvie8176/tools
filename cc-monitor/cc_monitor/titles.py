"""Local title override (#1764).

RC env-spawned sessions (the GUI's set) have no local ``custom-title`` — the real title lives
cloud-side only. This provides a hand-maintained local map so the dashboard can show a human
title without the cloud API. Keyed by ``sessionId`` (uuid) OR ``bridgeSessionId`` (session_xxx).

Title resolution precedence (applied in collect): override -> custom-title -> '' (cloud-side).
"""
from __future__ import annotations

import json

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
