"""Context-window (200k vs 1M) resolution.

The true window is NOT in the transcript — the JSONL model field is always e.g.
``claude-opus-4-8``, never ``…[1m]`` — and it is NOT reliably in the worker's env either. Claude
Code appends the ``[1m]`` suffix at RUNTIME from an account-level entitlement predicate; on a
default install no ``ANTHROPIC_DEFAULT_<FAM>_MODEL`` exists at all, so an env-only reader sees a
plain model id and concludes 200k for every session. Claude Code's own OTel ``api_request`` event
strips the suffix too. The one local channel that carries the truth is the statusLine payload
(``context_window.context_window_size`` plus a suffixed ``model.id``), captured per session by
``install/statusline-capture.sh`` — see :mod:`cc_monitor.statusline`.

Sources are layered, strongest evidence first, so no blind spot dominates:

  1. worker env      — per-worker overrides (a ``[1m]`` default, the 1M kill switch, an honoured
                       ceiling). Exec-time evidence about the worker it was read from.
  2. statusLine      — this session's own sample (exact ``session_id``): direct observation.
  3. statusLine      — a same-family sample from ANY session. The entitlement predicate driving the
                       ``[1m]`` suffix is account-global, and cc-monitor's boundary is one account
                       on one host, so a sample generalises across sessions of that family. This is
                       what covers ``sdk-cli`` workers, which never render a statusLine.
  4. model options   — Claude Code's own ``additionalModelOptionsCache`` names fully-qualified ids
                       for families beyond the built-ins. It supplies a VALUE freely; certainty only
                       once a statusLine sample has proven the account really receives ``[1m]``.
  5. settings.json   — the ``env`` block, applied internally and thus absent from ``/proc``. Value
                       freely, certainty only for workers demonstrably started under it.
  6. peak ctx        — a HARD LOWER BOUND: usage can never exceed the real window, so a peak above
                       the resolved value proves 1M no matter what the other layers claimed.

When nothing above decides, the window is genuinely unknown and ``certain`` is ``False`` ('?' in
the UI). A bare ``claude-opus-4-8`` with a readable-but-empty env is exactly that case — it is NOT
evidence of a 200k window, which is the bug this layering replaces.
"""
from __future__ import annotations

import os
import re

from . import paths

# Shown (with '?') when nothing resolves the window — a placeholder for the percentage maths, never
# an assertion. Every real value comes from Claude Code itself: a statusLine `context_window_size`,
# or the `[<n>m]` suffix it appends to a model id.
BASELINE = 200_000
ONE_M = 1_000_000
_TRUE = frozenset({"1", "true", "yes", "on"})
# `[1m]` today, `[2m]` tomorrow — parse the magnitude rather than pattern-matching one literal.
_SUFFIX_RE = re.compile(r"\[(\d+)m\]", re.IGNORECASE)
# First purely-alphabetic segment after `claude-`: opus / sonnet / haiku / fable / whatever ships
# next. Deriving the family instead of listing it is the difference between a monitor that survives
# a model launch and one that silently pins the new family to the baseline (as the missing `fable`
# entry did). Handles vendor-prefixed ids (`us.anthropic.claude-opus-…`) and legacy date-first ids.
_FAMILY_RE = re.compile(r"claude[-_]([a-z0-9.\-]+)")
# Any ANTHROPIC_DEFAULT_<FAMILY>_MODEL, anchored so the sibling *_MODEL_NAME / *_DESCRIPTION /
# *_SUPPORTED_CAPABILITIES keys and ANTHROPIC_DEFAULT_HEADERS (auth headers) never match. Matching
# the shape rather than an enumerated set is what lets a new family's default be honoured on day 0.
_MODEL_KEY_RE = re.compile(r"^ANTHROPIC_DEFAULT_[A-Z0-9]+_MODEL$")
_FLAG_KEYS = frozenset({
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    # The 1M kill switch. Per-worker, so it is the one thing that can legitimately contradict the
    # account-global statusLine generalisation (layer 3) — without reading it that inference would
    # be unsound.
    "CLAUDE_CODE_DISABLE_1M_CONTEXT",
    # Gates whether CLAUDE_CODE_MAX_CONTEXT_TOKENS applies to a first-party model (see _ceiling).
    "DISABLE_COMPACT",
})


def is_model_env_key(key: str) -> bool:
    """Whether an env key is window-relevant and display-safe.

    Public: settings.model_env() filters the settings.json `env` block by the SAME predicate, so the
    two env-derived window sources (proc environ + settings env-block) stay in lockstep.
    """
    return key in _FLAG_KEYS or bool(_MODEL_KEY_RE.match(key))


def read_model_env(pid, proc_dir: str | None = None):
    """Model/context env keys from /proc/<pid>/environ, or None if unreadable.

    Deliberately narrow — only keys passing :func:`is_model_env_key` are kept, so secret env values
    are never surfaced (see feedback: never read plaintext secrets).
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
        if sep and is_model_env_key(key):
            env[key] = val
    return env


def family(model: str) -> str | None:
    """Model family derived from the id (``OPUS``, ``FABLE``, …), or None for a non-Claude model.

    Derived, not enumerated: a hard-coded list goes stale the day a family ships, which is exactly
    how every Fable session came to be pinned to the baseline window. The family drives both the
    ``ANTHROPIC_DEFAULT_<FAM>_MODEL`` lookup and the statusLine generalisation, so a miss here is a
    silent wrong answer, not a visible error.
    """
    m = _FAMILY_RE.search((model or "").lower())
    if not m:
        return None
    for token in re.split(r"[-_.]", m.group(1)):
        if token.isalpha():  # skip version/date segments: claude-3-5-sonnet-…, …-opus-4-8
            return token.upper()
    return None


def suffix_window(model_id: str) -> int | None:
    """Window encoded in a model id's ``[<n>m]`` suffix (``[1m]`` -> 1_000_000), else None.

    Claude Code appends this at runtime from an account-level entitlement predicate. Reading the
    magnitude rather than matching the literal ``[1m]`` keeps a future ``[2m]`` from resolving to
    the baseline.
    """
    m = _SUFFIX_RE.search(model_id or "")
    return int(m.group(1)) * 1_000_000 if m else None


def _truthy(val) -> bool:
    return isinstance(val, str) and val.strip().lower() in _TRUE


def _ceiling(env, model) -> int | None:
    """``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` if Claude Code would actually honour it, else None.

    The CLI applies it in exactly two cases: when compaction is disabled outright, or when the
    resolved model is not a first-party ``claude-*`` id. Treating it as an unconditional override
    (as this module once did) reports a ceiling the running session is not subject to.
    """
    try:
        mx = int(env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS", ""))
    except (TypeError, ValueError):
        return None  # str.isdigit() is True for '²' etc., which int() then rejects — never crash
    if mx <= 0:
        return None
    if _truthy(env.get("DISABLE_COMPACT")):
        return mx
    return None if (model or "").strip().lower().startswith("claude-") else mx


def _from_env(env, model):
    """``(window, certain, authoritative)`` from the env alone — no peak, no calibration.

    ``authoritative`` marks an honoured explicit ceiling: it must NOT be raised by the peak lower
    bound, or a stale pre-throttle peak would clobber a deliberately lowered window.
    """
    if env is None:
        return BASELINE, False, False  # unreadable: no evidence either way
    mx = _ceiling(env, model)
    if mx is not None:
        return mx, True, True
    if _truthy(env.get("CLAUDE_CODE_DISABLE_1M_CONTEXT")):
        return BASELINE, True, False  # explicit per-worker kill switch: 200k, and we know it
    fam = family(model)
    effective = (env.get(f"ANTHROPIC_DEFAULT_{fam}_MODEL", "") if fam else "") or model or ""
    sfx = suffix_window(effective)
    return (sfx, True, False) if sfx else (BASELINE, False, False)


def _apply_peak(win, certain, peak_ctx, known=()):
    """Raise ``win`` to clear an observed peak. Usage can never exceed the real window.

    Promotes to the smallest window this host has actually SEEN that clears the peak (Claude Code's
    own numbers, via statusLine), falling back to ``ONE_M``. The old rule — "peak above 200k, so
    exactly 1M" — baked today's tiers in; a peak above every candidate now yields the peak itself,
    flagged, because we know the window is at least that but cannot name it.
    """
    peak = peak_ctx or 0
    if peak <= win:
        return win, certain
    bigger = sorted(w for w in {*known, ONE_M} if w > peak)
    return (bigger[0], True) if bigger else (peak, False)


def resolve_window(env, model, peak_ctx):
    """Env-layer resolution. Returns ``(window, certain)``; ``certain=False`` means "unknown".

    ``env`` is the dict from :func:`read_model_env` (``None`` if unreadable). A readable env that
    simply carries no model keys is NOT evidence of a 200k window — Claude Code appends the ``[1m]``
    suffix at runtime and needs no env at all — so it yields the baseline VALUE with
    ``certain=False``.
    """
    win, certain, authoritative = _from_env(env, model)
    return (win, certain) if authoritative else _apply_peak(win, certain, peak_ctx)


def _known_windows(cal):
    """Every window value Claude Code has actually reported here — the peak-promotion candidates."""
    if cal is None:
        return ()
    return {w for w in (*(cal.families or {}).values(), *(cal.options or {}).values()) if w}


def _from_calibration(cal, model, session_id):
    """``(window, certain)`` from the statusLine calibration, or ``None`` if it cannot decide.

    Layer 2 (this session's own sample) and layer 3 (a same-family sample from another session) are
    both ``certain``: the value is Claude Code's own ``context_window_size`` and the entitlement
    behind it is account-global. Layer 4 (the model-options cache) supplies a value but defers
    certainty until some sample has proven the account actually receives the ``[1m]`` suffix.
    """
    if cal is None:
        return None
    rec = (cal.sessions or {}).get(session_id) if session_id else None
    if rec and rec.get("win"):
        return rec["win"], True
    fam = family(model)
    if fam is None:
        return None
    fam_win = (cal.families or {}).get(fam)
    if fam_win:
        return fam_win, True
    opt_win = (cal.options or {}).get(fam)
    if opt_win:
        return opt_win, bool(cal.one_m_seen)
    return None


def resolve(proc_env, settings_env, model, peak_ctx, settings_trusted, cal=None, session_id=None):
    """Full window resolution across all layers. Returns ``(window, certain)``.

    ``cal`` is the :class:`cc_monitor.statusline.Calibration` (``None`` when the statusLine capture
    is not installed — the layering then degrades to env + peak, which on a default install cannot
    distinguish 1M from 200k and so reports '?' rather than a confident wrong answer).

    Precedence rationale:

    - A per-worker env override is exec-time evidence about THIS worker, and outranks any
      account-level generalisation.
    - ``proc_env is None`` (permission/hidepid/gone) means a possible override went unobserved, so
      the settings block may not fabricate certainty for it. A statusLine sample keyed to that very
      ``session_id`` is still direct observation of the session itself, and does apply.
    - The peak lower bound is applied ONCE, at the end, against every window this host has seen.
    """
    win, certain, authoritative = _from_env(proc_env, model)
    if authoritative:
        return win, certain
    if not certain:
        hit = _from_calibration(cal, model, session_id)
        if hit is not None:
            win, certain = hit
        elif proc_env is not None and settings_env:
            # The settings.json env block is applied internally and never reaches /proc. It grants a
            # VALUE freely but certainty only with evidence: the worker demonstrably started under
            # the current settings, or usage already proves the larger window.
            s_win, _, s_auth = _from_env({**settings_env, **proc_env}, model)
            if s_auth or s_win > win:
                proven = (peak_ctx or 0) > win
                win, certain = s_win, bool(settings_trusted or proven)
                if s_auth:
                    return win, certain  # a settings ceiling is still a ceiling
    return _apply_peak(win, certain, peak_ctx, known=_known_windows(cal))
