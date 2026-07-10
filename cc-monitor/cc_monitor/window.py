"""Context-window resolution — declared, bounded by observation, never guessed.

The window is NOT recoverable from anything Claude Code writes on the render path. Its transcript
``message.model`` is bare, its OTel ``api_request`` event strips the ``[<n>m]`` suffix, and a
default install carries no ``ANTHROPIC_DEFAULT_*_MODEL`` env at all — the CLI appends the suffix at
RUNTIME from an account-level entitlement predicate. Any rule inferred from those inputs is a rule
that silently stops holding, which is exactly how every session came to render a confident 200k.

So resolution layers three things, strongest evidence first:

  1. worker env    — per-worker overrides: a ``[<n>m]`` default, the ``CLAUDE_CODE_DISABLE_1M_CONTEXT``
                     kill switch, an honoured ``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` ceiling. Exec-time
                     evidence about the worker it was read from.
  2. declaration   — the operator's ``model_id -> window`` map, prefilled from evidence by
                     ``cc-monitor models --detect`` (see :mod:`cc_monitor.windows`).
  3. peak ctx      — a HARD LOWER BOUND. Usage can never exceed the real window, so a peak above the
                     resolved value proves it wrong: the window is promoted, and when the value it
                     overrode was a declaration, the row is flagged as CONFLICTING so the operator
                     sees that their map is stale rather than having it silently corrected.

(The settings.json ``env`` block sits under the worker env as a fallback: Claude Code applies it
internally so it never reaches ``/proc``, and a ``claude --resume`` worker's exec env lacks it.)

Nothing decides -> ``certain`` is ``False`` and the UI shows '?'. A readable env with no model keys
is absence of evidence, not evidence of a 200k window.

Nothing here is enumerated: the family is derived from the model id and the window from the
magnitude in the suffix, so a model launch needs no code change. A hard-coded family list is how
Fable sessions were pinned to the baseline for as long as they were.
"""
from __future__ import annotations

import os
import re

from . import paths

# Shown (with '?') when nothing resolves the window — a placeholder for the percentage maths, never
# an assertion. A real value comes from the operator's declaration, a `[<n>m]` suffix Claude Code
# put in the env, or an observed peak; never from this constant.
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
    # The 1M kill switch. Per-worker, so it can legitimately contradict a per-model declaration:
    # the declaration cannot know that one worker was launched with 1M disabled.
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
    how every Fable session came to be pinned to the baseline window. The family drives the
    ``ANTHROPIC_DEFAULT_<FAM>_MODEL`` lookup and the model-options prefill, so a miss here is a
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
    """``(window, certain, authoritative)`` from the env alone — no peak, no declaration.

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


def promote_to_clear_peak(win, certain, peak_ctx, known=()):
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
    return (win, certain) if authoritative else promote_to_clear_peak(win, certain, peak_ctx)


def resolve(proc_env, settings_env, model, peak_ctx, settings_trusted, declared=None, known=()):
    """Resolve one session's window. Returns ``(window, certain, conflict)``.

    ``declared`` is the operator's window for this exact model id (``None`` = undeclared -> '?').
    ``conflict`` is True only when a declaration was contradicted by observed usage: the value is
    corrected upward, and the caller surfaces the disagreement rather than hiding it.

    Precedence rationale:

    - A per-worker env override is exec-time evidence about THIS worker and outranks the declaration,
      which is per-model and cannot know that one worker was launched with the kill switch set.
    - ``proc_env is None`` (permission / hidepid / gone) means a possible override went unobserved,
      so the settings block may not fabricate certainty for it.
    - The peak lower bound applies last, against ``known`` — every window the operator has declared
      for any model — so a promotion lands on a real tier rather than a hard-coded 1M.
    """
    win, certain, authoritative = _from_env(proc_env, model)
    if authoritative:
        return win, certain, False
    used_declared = False
    if not certain:
        if declared:
            win, certain, used_declared = declared, True, True
        elif proc_env is not None and settings_env:
            # settings.json's env block is applied internally and never reaches /proc. It grants a
            # VALUE freely but certainty only with evidence: the worker demonstrably started under
            # the current settings, or usage already proves the larger window.
            s_win, _, s_auth = _from_env({**settings_env, **proc_env}, model)
            if s_auth or s_win > win:
                proven = (peak_ctx or 0) > win
                win, certain = s_win, bool(settings_trusted or proven)
                if s_auth:
                    return win, certain, False  # a settings ceiling is still a ceiling

    final, final_certain = promote_to_clear_peak(win, certain, peak_ctx, known=known)
    # Only usage can contradict a declaration we actually used. A per-worker env override that
    # supersedes the declaration is not a conflict — it is the override doing its job.
    return final, final_certain, used_declared and final != declared
