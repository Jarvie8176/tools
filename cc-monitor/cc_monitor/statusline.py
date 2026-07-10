"""Read the per-session statusLine samples — the only local source of the true context window.

``install/statusline-capture.sh`` is invoked by Claude Code once per TUI render and writes one small
JSON file per ``session_id`` into :data:`cc_monitor.paths.STATUSLINE_DIR`. Each file carries the
window Claude Code itself computed for that session, the ``[1m]``-suffixed ``model.id``, and that
session's effort level.

Two facts shape how the samples are used:

* Only TUI sessions render a statusLine. ``sdk-cli`` workers — the bulk of a cc-session fleet —
  never call the script, so a per-session join alone would leave most rows unresolved.
* The predicate that decides whether Claude Code appends ``[1m]`` is account-level, not per-session.

So a sample is generalised into a per-FAMILY window: one Opus sample resolves every Opus session on
the box. That inference holds only within cc-monitor's stated boundary — a single account on a
single host — and only until a worker sets ``CLAUDE_CODE_DISABLE_1M_CONTEXT``, which
:mod:`cc_monitor.window` reads from ``/proc`` and lets outrank this layer.

Absent directory / unreadable files yield an EMPTY calibration rather than an error, matching the
absent≠error contract of :mod:`cc_monitor.otel` and :mod:`cc_monitor.ccsession`.
"""
from __future__ import annotations

import glob
import json
import os
from typing import NamedTuple

from . import paths, window

# Samples are tiny (~200B) but the directory gains one file per TUI session, forever. Parse only the
# newest few hundred: that spans years of samples, and the per-family calibration only ever needs
# the most recent one of each family.
_MAX_SAMPLES = 500
# `additionalModelOptionsCache` lives in ~/.claude.json, which also holds per-project history and
# grows without bound. The serve loop calls calibrate() every refresh, so cache the parse by mtime.
_OPTIONS_CACHE: dict = {"key": None, "value": {}}


class Calibration(NamedTuple):
    """What the statusLine samples let us conclude about windows.

    ``sessions``  — ``{session_id: {"win", "model_id", "effort", "ts"}}``, direct observations.
    ``families``  — ``{FAMILY: window}`` from the most recent sample of that family.
    ``options``   — ``{FAMILY: window}`` implied by Claude Code's model-options cache.
    ``one_m_seen``— some sample carried a ``[1m]`` id, proving the account receives the suffix.
    """

    sessions: dict
    families: dict
    options: dict
    one_m_seen: bool


EMPTY = Calibration({}, {}, {}, False)


def read_samples(dir_path: str | None = None) -> dict:
    """``{session_id: record}`` from the sample directory; ``{}`` when absent/unreadable.

    A malformed or half-written file is skipped, never fatal: the capture writes atomically, but a
    stale file from an older schema must not wedge the collector.
    """
    root = dir_path or paths.STATUSLINE_DIR
    out = {}
    paths_found = glob.glob(os.path.join(root, "*.json"))
    if len(paths_found) > _MAX_SAMPLES:
        paths_found.sort(key=lambda p: _mtime(p), reverse=True)
        paths_found = paths_found[:_MAX_SAMPLES]
    for path in paths_found:
        try:
            with open(path) as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id") or os.path.basename(path)[:-len(".json")]
        win = rec.get("win")
        out[sid] = {
            "win": win if isinstance(win, int) and win > 0 else None,
            "model_id": rec.get("model_id") if isinstance(rec.get("model_id"), str) else None,
            "effort": rec.get("effort") if isinstance(rec.get("effort"), str) else None,
            "ts": rec.get("ts") if isinstance(rec.get("ts"), (int, float)) else 0.0,
        }
    return out


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _stamp(path: str):
    """(mtime, size) — size guards against a rewrite landing inside one mtime tick."""
    try:
        st = os.stat(path)
    except OSError:
        return (0.0, -1)
    return (st.st_mtime, st.st_size)


def model_options(path: str | None = None) -> dict:
    """``{FAMILY: window}`` from ``~/.claude.json``'s ``additionalModelOptionsCache``.

    Claude Code caches the fully-qualified ids it offers for families beyond the built-ins, and a
    1M-entitled account sees them suffixed. Only ``value`` is read — the surrounding file holds
    oauth account data and is never surfaced. Absent/unreadable yields ``{}``.
    """
    src = path or paths.CLAUDE_JSON
    key = (src, _stamp(src))
    if _OPTIONS_CACHE["key"] == key:
        return _OPTIONS_CACHE["value"]
    try:
        with open(src) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        _OPTIONS_CACHE.update(key=key, value={})
        return {}
    opts = data.get("additionalModelOptionsCache") if isinstance(data, dict) else None
    if not isinstance(opts, list):
        _OPTIONS_CACHE.update(key=key, value={})
        return {}
    out = {}
    for opt in opts:
        if not isinstance(opt, dict):
            continue
        val = opt.get("value")
        if not isinstance(val, str):
            continue
        fam = window.family(val)
        win = window.suffix_window(val)
        if fam and win:
            out[fam] = win
    _OPTIONS_CACHE.update(key=key, value=out)
    return out


def calibrate(dir_path: str | None = None, claude_json: str | None = None) -> Calibration:
    """Build the :class:`Calibration` read once per collect cycle and joined per row."""
    samples = read_samples(dir_path)
    families: dict[str, tuple[int, float]] = {}
    one_m_seen = False
    for rec in samples.values():
        mid = rec.get("model_id") or ""
        if window.suffix_window(mid):
            one_m_seen = True  # the account demonstrably receives the entitlement suffix
        fam = window.family(mid)
        win = rec.get("win")
        if not fam or not win:
            continue
        # Latest-wins per family: entitlement can change (plan change, kill switch), and a stale
        # sample must not outvote a fresh one that saw the new window.
        prev = families.get(fam)
        if prev is None or rec["ts"] >= prev[1]:
            families[fam] = (win, rec["ts"])
    return Calibration(
        sessions=samples,
        families={f: w for f, (w, _) in families.items()},
        options=model_options(claude_json),
        one_m_seen=one_m_seen,
    )


def effort_for(cal: Calibration, session_id: str) -> str | None:
    """This session's effort as the statusLine reported it, or ``None``.

    Only an exact ``session_id`` match counts — unlike the window, effort is genuinely per-session
    and must never be generalised across sessions.
    """
    rec = (cal.sessions or {}).get(session_id)
    return rec.get("effort") if isinstance(rec, dict) else None
