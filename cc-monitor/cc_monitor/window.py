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


def merge_model_env(proc_env: dict | None, settings_env: dict | None):
    """Overlay the worker's exec-time ``/proc`` env on the settings.json ``env``-block defaults.

    The settings.json ``env`` block (e.g. ``ANTHROPIC_DEFAULT_OPUS_MODEL=…[1m]``) is applied
    INTERNALLY by Claude Code to every session, so it never appears in ``/proc/<pid>/environ`` — a
    ``claude --resume`` worker launched from a plain shell has an empty model env THERE yet still
    runs at the settings-configured window. Reading ``/proc`` alone under-reports such a worker as
    200k (and, worse, marks it certain). Here ``proc`` (a spawner override, authoritative when
    present) wins per key; ``settings`` fills only the keys ``proc`` lacks.

    Returns ``None`` only when ``/proc`` was unreadable AND ``settings`` had nothing — the one case
    the window is still locally unknowable, which :func:`resolve_window` flags ``'?'``. A readable
    but empty ``proc`` env stays a dict (not None): we DID observe the worker's env and found no
    override, so with an equally-empty settings block 200k is a certain answer, not a guess."""
    if proc_env is None:
        return dict(settings_env) if settings_env else None
    return {**(settings_env or {}), **proc_env}


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
