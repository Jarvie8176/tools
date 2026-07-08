"""Parse a Claude Code transcript JSONL into the fields the dashboard needs.

Context size is derived from the input-side of the last assistant ``usage``
(``input + cache_read + cache_creation``) — this is unaffected by the known ``output_tokens``
undercount (anthropics/claude-code#27361). TITLE (human ``custom-title``) and LAST-PROMPT (the
actual last user turn) are returned separately: the last prompt drifts and is not an identity.

Transcripts are **append-only** and grow to tens of MB, so the peak-context high-water scan is the
serve loop's cost centre (a 40MB re-parse is ~0.5s). ``parse_incremental`` folds only the bytes
appended since the previous parse into the prior accumulators — turning that re-parse into ~ms —
and falls back to a full parse when the file shrank or rotated (the append-only invariant broke).
"""
from __future__ import annotations

import json
import os

MAX_FULL_PARSE = 60 * 1024 * 1024  # skip cumulative sum for transcripts bigger than this
MAX_TEXT = 512  # cap retained title/prompt — the UI shows <=70 chars, and a pasted diff/log can
#               be megabytes per line; keeping full text for every row risks OOM.

# Fallback prefixes for transcripts that predate the `origin` field. The primary filter is
# structural (origin.kind != "human"); these only catch injected turns when origin is absent,
# and are precise enough not to drop a genuine prompt that merely starts with '<'.
_ENVELOPE_PREFIXES = ("<system-reminder", "<local-command", "[Request interrupted")


def user_text(content) -> str | None:
    """Human-typed text of a user turn, or None. Skips tool_result blocks and system-injected
    envelopes so a derived label reflects an actual prompt, not tool plumbing."""
    text = None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                text = block["text"]
                break
            if isinstance(block, str):
                text = block
                break
    if not text:
        return None
    text = text.strip()
    if text.startswith(_ENVELOPE_PREFIXES):
        return None
    return text


def _num(v) -> int:
    """Coerce a token field to int. A present-but-null value (a future CC version could emit a null
    token count) must not crash the cumulative sum / context calc — ``None + int`` would raise."""
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _ctx_of(usage: dict) -> int:
    return (
        _num(usage.get("input_tokens"))
        + _num(usage.get("cache_read_input_tokens"))
        + _num(usage.get("cache_creation_input_tokens"))
    )


def empty(mtime: float = 0.0) -> dict:
    return {
        "model": None, "ctx": 0, "peak_ctx": 0, "custom_title": "",
        "initial_prompt": "", "last_prompt": "",
        "cum_input": 0, "cum_output": 0, "cum_cache": 0, "full": False,
        "mtime": mtime, "size": 0, "_offset": 0,
    }


def _resumable(prev, size: int) -> bool:
    """True when ``prev`` can be extended in place: it carries a byte offset and the file only grew
    (append-only intact). A shrunk/rotated file (size < prev size) or a missing offset forces a full
    re-parse from 0 — otherwise we'd resume mid-record into unrelated bytes."""
    return (
        isinstance(prev, dict) and "_offset" in prev
        and prev.get("size", 0) <= size and prev["_offset"] <= size
    )


def _parse(path: str, full: bool, prev: dict | None) -> dict:
    """Core fold. With ``prev`` resumable, seed the accumulators from it and read only the bytes
    after ``prev['_offset']``; otherwise parse the whole file from 0. Reads in binary and advances
    the offset only past the last complete (newline-terminated) line — a trailing partial line from
    a mid-write transcript is left unconsumed and picked up once the newline lands."""
    try:  # stat once, up front — a transcript can rotate/vanish mid-read (hot file)
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
    except OSError:
        return empty()

    if _resumable(prev, size):
        start = prev["_offset"]
        last_model = prev.get("model")
        ctx = prev.get("ctx", 0)
        peak_ctx = prev.get("peak_ctx", 0)
        custom_title = prev.get("custom_title") or None
        first_user = prev.get("initial_prompt") or None
        last_user = prev.get("last_prompt") or None
        cum_input = prev.get("cum_input", 0)
        cum_output = prev.get("cum_output", 0)
        cum_cache = prev.get("cum_cache", 0)
    else:
        start = 0
        last_model = None
        ctx = peak_ctx = 0
        custom_title = first_user = last_user = None
        cum_input = cum_output = cum_cache = 0

    do_full = full and size <= MAX_FULL_PARSE
    offset = start
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            chunk = fh.read()
    except OSError:
        return empty()  # vanished between stat and read
    nl = chunk.rfind(b"\n")  # only fold complete lines; leave a trailing partial for next round
    text = chunk[:nl + 1].decode("utf-8", "ignore") if nl >= 0 else ""
    if nl >= 0:
        offset = start + nl + 1

    for line in text.splitlines():
        if "customTitle" not in line and '"assistant"' not in line and '"user"' not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        etype = ev.get("type")
        if etype == "custom-title" and ev.get("customTitle"):
            custom_title = ev["customTitle"]  # human-set; last one wins
            continue
        if etype == "user":
            # Structural gate: only human-origin turns are prompts. Harness-injected turns
            # (task-notification, hook output, ...) carry origin.kind != "human". origin can
            # be any JSON type in a malformed line, so guard the .get with isinstance.
            org = ev.get("origin")
            kind = org.get("kind") if isinstance(org, dict) else None
            if kind and kind != "human":
                continue
            # message may be present-but-null / a non-dict in a malformed line — guard the
            # .get chain the same way `origin` is guarded above, or the whole parse crashes.
            m = ev.get("message")
            txt = user_text(m.get("content") if isinstance(m, dict) else None)
            if txt:
                if first_user is None:
                    first_user = txt  # opening human prompt (stable identity; keep first)
                last_user = txt  # actual last user prompt (overwrite)
            continue
        if etype != "assistant":
            continue
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):  # present-but-null / non-dict usage must not crash
            continue
        if msg.get("model") and msg["model"] != "<synthetic>":
            last_model = msg["model"]
        ctx = _ctx_of(usage)  # last valid assistant usage wins (context = most recent turn)
        if ctx > peak_ctx:
            peak_ctx = ctx
        if do_full:
            cum_input += _num(usage.get("input_tokens"))
            cum_output += _num(usage.get("output_tokens"))
            cum_cache += _num(usage.get("cache_read_input_tokens")) + _num(
                usage.get("cache_creation_input_tokens")
            )

    if not do_full:  # oversized transcript — mirror the full-parse contract (cum not tracked)
        cum_input = cum_output = cum_cache = 0

    return {
        "model": last_model,
        "ctx": ctx,
        "peak_ctx": peak_ctx,
        "custom_title": " ".join(custom_title.split())[:MAX_TEXT] if custom_title else "",
        "initial_prompt": " ".join(first_user.split())[:MAX_TEXT] if first_user else "",
        "last_prompt": " ".join(last_user.split())[:MAX_TEXT] if last_user else "",
        "cum_input": cum_input, "cum_output": cum_output, "cum_cache": cum_cache,
        "full": do_full, "mtime": mtime, "size": size, "_offset": offset,
    }


def parse(path: str, full: bool = True) -> dict:
    """Extract model / context / peak / cumulative tokens / title / last-prompt from a JSONL."""
    return _parse(path, full, None)


def parse_incremental(path: str, prev: dict, full: bool = True) -> dict:
    """Extend a prior ``parse`` result with only the bytes appended since — or fall back to a full
    parse if the append-only invariant broke (see ``_resumable``). Equivalent to ``parse`` output."""
    return _parse(path, full, prev)
