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
    """Override title for a session, by sessionId or bridgeSessionId, else ''."""
    if session_id and session_id in overrides:
        return overrides[session_id]
    if bridge_id and bridge_id in overrides:
        return overrides[bridge_id]
    return ""
