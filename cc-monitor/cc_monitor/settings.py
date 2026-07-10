"""Read Claude Code's own settings.json for the current reasoning effort level.

Effort is NOT in the transcript or the worker environ (checked: neither the JSONL nor
``/proc/<pid>/environ`` carries it) — the only local source is Claude Code's ``settings.json``
``effortLevel``. That file is per-user/global, so this is a single header fact, not a per-session
column: the dashboard shows the effort the CLI is currently configured with, not a per-worker value
it cannot observe (same honesty rule as the window '?' and the cloud-side title gap).

Only the display-safe ``effortLevel`` scalar is returned. settings.json also holds env/secrets, so
the whole file is never surfaced; a missing/unreadable file or key yields ``None`` (UI shows '?').
"""
from __future__ import annotations

import json
import os

from . import paths, window

_MAX = 16  # effort labels are short (low/medium/high/xhigh/max); cap a malformed value defensively


def _read(path: str | None) -> dict:
    """settings.json parsed to a dict, or ``{}`` on any read/parse error or non-object top level."""
    try:
        with open(path or paths.SETTINGS_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def effort_level(path: str | None = None) -> str | None:
    """Return the configured effort level string, or ``None`` if unset/unreadable.

    Not validated against a fixed enum — the label set can drift across CLI versions, and render
    already strips control chars — but length-capped so a hand-edited garbage value can't bloat the
    header.
    """
    val = _read(path).get("effortLevel")
    return val[:_MAX] if isinstance(val, str) and val else None


def model_env(path: str | None = None) -> dict:
    """Window-relevant keys from settings.json's ``env`` block (``{}`` if absent).

    Claude Code applies this ``env`` block INTERNALLY to every session, so these keys never reach
    ``/proc/<pid>/environ`` (see :func:`cc_monitor.window.merge_model_env`). Filtered to exactly
    :func:`window.is_model_env_key` and string values — never other env entries (the block also holds
    PATH, and could hold secrets), so nothing sensitive is surfaced."""
    env = _read(path).get("env")
    if not isinstance(env, dict):
        return {}
    return {k: v for k, v in env.items() if window.is_model_env_key(k) and isinstance(v, str)}


def file_mtime(path: str | None = None) -> float | None:
    """settings.json mtime (epoch seconds), or ``None`` if the file is absent.

    Used to gate the model_env fallback's certainty: only a worker that started AT OR AFTER this
    mtime demonstrably ran under the current settings (see :func:`cc_monitor.window.resolve`)."""
    try:
        return os.path.getmtime(path or paths.SETTINGS_FILE)
    except OSError:
        return None
