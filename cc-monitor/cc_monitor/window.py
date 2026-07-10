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

BASELINE = 200_000
ONE_M = 1_000_000
_1M_RE = re.compile(r"\[1m\]", re.IGNORECASE)
_TRUE = frozenset({"1", "true", "yes", "on"})
_FAMILIES = ("opus", "sonnet", "haiku", "fable")
# Exact keys only — a prefix match would also capture ANTHROPIC_DEFAULT_HEADERS (auth headers).
# Public: settings.model_env() filters the settings.json `env` block by the SAME set, so the two
# env-derived window sources (proc environ + settings env-block) stay in lockstep.
MODEL_ENV_KEYS = frozenset(
    [f"ANTHROPIC_DEFAULT_{f.upper()}_MODEL" for f in _FAMILIES] + [
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
        # The 1M kill switch. Per-worker, so it is the one thing that can legitimately contradict
        # the account-global statusLine generalisation (layer 3) — without reading it that
        # inference would be unsound.
        "CLAUDE_CODE_DISABLE_1M_CONTEXT",
        # Gates whether CLAUDE_CODE_MAX_CONTEXT_TOKENS applies to a first-party model (see _ceiling).
        "DISABLE_COMPACT",
    ]
)


def read_model_env(pid, proc_dir: str | None = None):
    """Model/context env keys from /proc/<pid>/environ, or None if unreadable.

    Deliberately narrow — only the keys in :data:`MODEL_ENV_KEYS` are kept, so secret env values are
    never surfaced (see feedback: never read plaintext secrets).
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


def family(model: str) -> str | None:
    """Model family (``OPUS``/``SONNET``/``HAIKU``/``FABLE``), or None if unrecognised.

    Mirrors Claude Code's own family list. Omitting ``fable`` silently pinned every Fable session to
    the baseline window, since the family drives both the env lookup and the statusLine
    generalisation.
    """
    m = (model or "").lower()
    for fam in _FAMILIES:
        if fam in m:
            return fam.upper()
    return None


def has_1m(model_id: str) -> bool:
    """True when a model id carries the ``[1m]`` suffix Claude Code appends for a 1M window."""
    return bool(model_id) and bool(_1M_RE.search(model_id))


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


def resolve_window(env, model, peak_ctx):
    """Env-layer resolution. Returns ``(window, certain)``; ``certain=False`` means "unknown".

    ``env`` is the dict from :func:`read_model_env` (``None`` if unreadable). A readable env that
    simply carries no model keys is NOT evidence of a 200k window — Claude Code needs no env at all
    to run a 1M session — so it yields the baseline VALUE with ``certain=False``.
    """
    if env is None:
        # Env unreadable: fall back to peak alone. 1M only if usage already proves it.
        win, certain = (ONE_M, True) if (peak_ctx or 0) > BASELINE else (BASELINE, False)
    else:
        mx = _ceiling(env, model)
        if mx is not None:
            # An honoured ceiling is authoritative — return BEFORE the peak lower bound, so a stale
            # pre-throttle peak cannot clobber a deliberately lowered window.
            return mx, True
        if _truthy(env.get("CLAUDE_CODE_DISABLE_1M_CONTEXT")):
            win, certain = BASELINE, True  # explicit per-worker kill switch: 200k, and we know it
        else:
            fam = family(model)
            effective = (env.get(f"ANTHROPIC_DEFAULT_{fam}_MODEL", "") if fam else "") or model or ""
            win, certain = (ONE_M, True) if _1M_RE.search(effective) else (BASELINE, False)
    if (peak_ctx or 0) > win:  # observed usage overrides any smaller inferred window
        win, certain = ONE_M, True
    return win, certain


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
    - Otherwise the calibration decides; the settings block is the last value source before the peak
      lower bound.
    """
    win, certain = resolve_window(proc_env, model, peak_ctx)
    if certain:
        return win, certain  # env (or the peak lower bound) already produced hard evidence

    hit = _from_calibration(cal, model, session_id)
    if hit is not None:
        win, certain = hit
        if (peak_ctx or 0) > win:
            win, certain = ONE_M, True
        return win, certain

    if proc_env is None or not settings_env:
        return win, certain  # unobservable env / nothing left to add

    s_win, _ = resolve_window({**settings_env, **proc_env}, model, peak_ctx)
    if s_win <= win:
        return win, certain  # settings only ever raises here; a lower ceiling needs evidence
    return s_win, bool(settings_trusted or (peak_ctx or 0) > BASELINE)
