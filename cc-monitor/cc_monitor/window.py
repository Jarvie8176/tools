"""Context-window (200k vs 1M) resolution.

The true window is NOT in the transcript — the JSONL model field is always e.g.
``claude-opus-4-8`` with no ``[1m]`` suffix. It IS recoverable from the worker's env
(``ANTHROPIC_DEFAULT_<FAM>_MODEL`` carries ``[1m]``), reproducing Claude Code's own rule
(``rE -> WIi``: ``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` override, then the ``/\\[1m\\]/i`` regex).

Two independent signals are combined so neither blind spot dominates:
  1. worker env  — authoritative for low-usage sessions the peak can't classify
  2. peak ctx    — a HARD LOWER BOUND: usage can't exceed the real window, so a peak above
                   the env-derived value proves 1M (catches workers that got [1m] via CLI/other
                   means where the env var is absent).
"""
from __future__ import annotations

import os
import re

from . import paths

BASELINE = 200_000
ONE_M = 1_000_000
_1M_RE = re.compile(r"\[1m\]", re.IGNORECASE)
# Exact keys only — a prefix match would also capture ANTHROPIC_DEFAULT_HEADERS (auth headers).
# Public: settings.model_env() filters the settings.json `env` block by the SAME set, so the two
# window sources (proc environ + settings env-block) stay in lockstep.
MODEL_ENV_KEYS = frozenset({
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
})


def read_model_env(pid, proc_dir: str | None = None):
    """Model/context env keys from /proc/<pid>/environ, or None if unreadable.

    Deliberately narrow — only ANTHROPIC_DEFAULT_* and CLAUDE_CODE_MAX_CONTEXT keys are
    kept, so secret env values are never surfaced (see feedback: never read plaintext secrets).
    """
    if not pid:
        return None
    proc_dir = proc_dir or paths.PROC_DIR
    try:
        with open(os.path.join(proc_dir, str(pid), "environ"), "rb") as fh:
            raw = fh.read().decode("utf-8", "ignore")
    except OSError:
        return None
    env = {}
    for kv in raw.split("\0"):
        key, sep, val = kv.partition("=")
        if sep and key in MODEL_ENV_KEYS:
            env[key] = val
    return env


def _family(model: str) -> str | None:
    m = (model or "").lower()
    if "opus" in m:
        return "OPUS"
    if "sonnet" in m:
        return "SONNET"
    if "haiku" in m:
        return "HAIKU"
    return None


def resolve_window(env, model, peak_ctx):
    """Return ``(window, certain)``.

    ``env`` is the dict from :func:`read_model_env` (``None`` if unreadable). ``certain`` is
    ``False`` only when the env is unreadable AND peak<=200k — the one case the window is truly
    unknowable locally (flagged '?' in the UI, resolvable via statusLine/OTel).
    """
    if env is not None:
        # An explicit ceiling is authoritative — return early, BEFORE the peak lower-bound, so a
        # stale pre-throttle peak can't clobber a deliberately lowered window. Parse defensively:
        # str.isdigit() is True for Unicode digits (e.g. '²') that int() then rejects.
        try:
            mx = int(env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS", ""))
        except ValueError:
            mx = 0
        if mx > 0:
            return mx, True
        fam = _family(model)
        effective = (env.get(f"ANTHROPIC_DEFAULT_{fam}_MODEL", "") if fam else "") or model or ""
        win, certain = (ONE_M, True) if _1M_RE.search(effective) else (BASELINE, True)
    else:
        # No env: fall back to peak alone. 1M only if usage already proves it.
        win, certain = (ONE_M, True) if (peak_ctx or 0) > BASELINE else (BASELINE, False)
    if (peak_ctx or 0) > win:  # observed usage overrides a too-small INFERRED window
        win, certain = ONE_M, True
    return win, certain


# Window "source" tags for the payload/UI — where a session's window value came from. Only the
# first three are real evidence; "candidate" is a detected snapshot; "unknown" is the locally-
# unknowable deadzone (env unreadable + low usage). The candidate write-gate keys off EVIDENCE.
SRC_MANUAL = "manual"       # operator override (models.json) — highest precedence
SRC_EVIDENCE = "evidence"   # resolve() decided it from proc env / settings / observed peak
SRC_CANDIDATE = "candidate"  # filled from an auto-detected candidate (deadzone only)
SRC_UNKNOWN = "unknown"     # nothing authoritative — UI shows '?'


def apply_model_window(ev_win, ev_certain, override_win, candidate_win):
    """Layer per-model operator override (top) + detected candidate (bottom) over the evidence.

    ``ev_win``/``ev_certain`` are the PURE-EVIDENCE result from :func:`resolve` (which never sees
    override/candidate). Precedence, high -> low: manual override > evidence > candidate. Returns
    ``(window, certain, source)``.

    - override (>0) is authoritative -> ``certain=True`` (operator sovereignty).
    - else if evidence is certain, it stands (proc/settings/peak decided it).
    - else a candidate fills the '?' deadzone — value shown, but ``certain=False`` since it is a
      prior snapshot, not live evidence; it NEVER overrides a certain evidence result above.
    - else the unknowable baseline (``ev_win``, ``certain=False``) with source 'unknown'.
    """
    if override_win and override_win > 0:
        return override_win, True, SRC_MANUAL
    if ev_certain:
        return ev_win, True, SRC_EVIDENCE
    if candidate_win and candidate_win > 0:
        return candidate_win, False, SRC_CANDIDATE
    return ev_win, ev_certain, SRC_UNKNOWN


def resolve(proc_env, settings_env, model, peak_ctx, settings_trusted):
    """Full window resolution layering the settings.json ``env`` block under the ``/proc`` env.

    The settings.json ``env`` block (e.g. ``ANTHROPIC_DEFAULT_OPUS_MODEL=…[1m]``) is applied
    INTERNALLY by Claude Code, so it never reaches ``/proc/<pid>/environ`` — a ``claude --resume``
    worker's exec env lacks it yet the worker still runs at the settings window. Reading ``/proc``
    alone under-reports such a worker as 200k. But settings.json is a GLOBAL, TIME-VARYING source,
    so it grants a WINDOW VALUE freely and CERTAINTY only with evidence:

    - ``proc_env`` is authoritative (exec-time evidence). If it already resolves a window > baseline
      (a spawner ``[1m]``/explicit ceiling, or peak proof), that answer stands — settings never
      overrides observed evidence.
    - ``proc_env is None`` (unreadable: permission/hidepid/gone) stays unknowable. We do NOT
      fabricate certainty from global settings for an env we couldn't observe — it may carry an
      unseen spawner override. Falls back to peak-only (``'?'`` unless usage proves it).
    - Otherwise (proc readable, resolved to plain baseline) the settings block may RAISE the window.
      That raise is ``certain`` only if ``settings_trusted`` (the worker demonstrably started under
      the current settings — mtime <= start) OR peak already proves the larger window; else ``'?'``.
    """
    win, certain = resolve_window(proc_env, model, peak_ctx)
    if proc_env is None or win != BASELINE or not settings_env:
        return win, certain  # unreadable / already-decided / nothing to add
    s_win, _ = resolve_window({**settings_env, **proc_env}, model, peak_ctx)
    if s_win <= win:
        return win, certain  # settings only ever raises here; a lower global ceiling needs evidence
    return s_win, bool(settings_trusted or (peak_ctx or 0) > BASELINE)
