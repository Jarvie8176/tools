"""Declared context window per model id — the operator's map, prefilled from evidence.

Claude Code does not persist the context window anywhere a monitor can read on the render path. It
appends the ``[<n>m]`` suffix to a model id at RUNTIME from an account-level entitlement predicate,
so the transcript's ``message.model`` is bare, its OTel ``api_request`` event is bare, and a default
install has no ``ANTHROPIC_DEFAULT_*_MODEL`` env at all. Every rule a monitor could infer from those
is a rule that silently stops holding.

So the window is **declared**, not inferred: ``~/.claude/cc-monitor-windows.json`` maps an exact
model id to its window. Two properties make that safe:

* The map is **prefilled mechanically** by :func:`detect` from the model ids actually present in the
  transcripts, so a model launch never needs a code change — it shows up in the file on the next
  ``cc-monitor models --detect``. A model with no entry resolves to '?' and is never guessed.
* A declaration can only ever be wrong in one direction that matters. Usage cannot exceed the real
  window, so an observed peak above the declared value PROVES the declaration wrong; the resolver
  promotes and flags the conflict (see :func:`cc_monitor.window.resolve`). The opposite error —
  declaring 1M for a 200k model — is not locally detectable by anything, which is precisely why the
  value is the operator's to assert rather than cc-monitor's to guess.

Keyed by the exact id (``claude-haiku-4-5-20251001``, not ``haiku``): a family-level default would
quietly extend one model's entitlement to the next model of that family.
"""
from __future__ import annotations

import glob
import json
import os
import tempfile

from . import paths, transcript, window


def load(path: str | None = None) -> dict:
    """``{model_id: window}`` for entries with a usable positive int; ``{}`` on missing/corrupt file.

    A ``null`` (or malformed) value means "declared unknown" and is dropped here, so the resolver
    sees no entry and reports '?'. That is the whole point of prefilling with ``null``: an operator
    who has not decided yet must not be represented as having decided.
    """
    path = path or paths.WINDOWS_FILE
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0}


def save(mapping: dict, path: str | None = None) -> None:
    """Atomically write the map (``None`` values preserved — they are the 'undecided' marker)."""
    path = path or paths.WINDOWS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".cc-monitor-windows.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(mapping, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _option_windows(path: str | None = None) -> dict:
    """``{FAMILY: window}`` from ``~/.claude.json``'s ``additionalModelOptionsCache``.

    Claude Code caches the fully-qualified ids it offers for families beyond the built-ins, suffix
    included, and refreshes them from the server. Read only here, never on the render path. Only
    ``value`` is touched — the surrounding file holds oauth account data.
    """
    try:
        with open(path or paths.CLAUDE_JSON) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    opts = data.get("additionalModelOptionsCache") if isinstance(data, dict) else None
    if not isinstance(opts, list):
        return {}
    out = {}
    for opt in opts:
        val = opt.get("value") if isinstance(opt, dict) else None
        if not isinstance(val, str):
            continue
        fam, win = window.family(val), window.suffix_window(val)
        if fam and win:
            out[fam] = win
    return out


def observed_peaks(projects_dir: str | None = None) -> dict:
    """``{model_id: highest input-side context ever recorded}`` across every transcript.

    A hard lower bound per model, and the strongest evidence available without asking Claude Code:
    a request whose input side reached N tokens proves that model's window is at least N.
    """
    root = projects_dir or paths.PROJECTS_DIR
    peaks: dict[str, int] = {}
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        try:
            with open(path) as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue  # a partial trailing line, or a schema we do not know
                    msg = rec.get("message")
                    if not isinstance(msg, dict):
                        continue
                    mid = msg.get("model")
                    if not isinstance(mid, str) or not mid.startswith("claude-"):
                        continue
                    ctx = transcript.input_side_tokens(msg.get("usage"))
                    if ctx > peaks.get(mid, 0):
                        peaks[mid] = ctx
        except OSError:
            continue
    return peaks


def suggest(peaks: dict, options: dict, existing: dict) -> dict:
    """``{model_id: window|None}`` — a value for every model seen, ``None`` where nothing proves one.

    Evidence, strongest first: an existing declaration (never silently overwritten), then the
    suffixed id Claude Code itself offers for that family, then the observed peak.

    A peak is evidence ONLY above the baseline. Below it the model may equally be a baseline model or
    a large-window one that never filled up, so the honest answer is ``None`` — "we cannot tell, you
    decide" — which renders as '?' until the operator fills it in. A peak above every window we know
    of is also ``None``: we have proven a floor we cannot name a tier for.
    """
    known = {w for w in (*options.values(), *existing.values()) if w}
    out: dict = {}
    for mid, peak in sorted(peaks.items()):
        if mid in existing:
            out[mid] = existing[mid]  # a declaration is never overwritten by a detect
            continue
        fam = window.family(mid)
        if fam and options.get(fam):
            out[mid] = options[fam]
            continue
        if peak > window.BASELINE:
            bigger = sorted(w for w in {*known, window.ONE_M} if w > peak)
            out[mid] = bigger[0] if bigger else None
        else:
            out[mid] = None
    return out


def detect(projects_dir: str | None = None, claude_json: str | None = None,
           path: str | None = None) -> dict:
    """Build the prefilled map without writing it. ``cc-monitor models --detect`` prints this."""
    return suggest(observed_peaks(projects_dir), _option_windows(claude_json), load(path))
