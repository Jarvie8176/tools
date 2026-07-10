"""Parse a Claude Code transcript JSONL into the fields the dashboard needs.

Context size is derived from the input-side of the last assistant ``usage``
(``input + cache_read + cache_creation``) — this is unaffected by the known ``output_tokens``
undercount (anthropics/claude-code#27361). TITLE (human ``custom-title``) and LAST-PROMPT (the
actual last user turn) are returned separately: the last prompt drifts and is not an identity.

Transcripts are **append-only** and grow to tens of MB, so the peak-context high-water scan is the
serve loop's cost centre (a 40MB re-parse is ~0.5s). ``parse_incremental`` folds only the bytes
appended since the previous parse into the prior accumulators — turning that re-parse into ~ms —
but only when the file is provably the same one, grown by appends: same ``(st_dev, st_ino)``
(catches rename-rotation), size not shrunk (catches truncation), and the byte the previous parse
stopped on is unchanged (catches a truncate-then-rewrite in the SAME inode). Any of those failing
forces a full re-parse from 0, so a rotated/rewritten transcript never inherits a stale accumulator.
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


def input_side_tokens(usage) -> int:
    """Input-side context of one assistant turn. Public: windows.detect() folds the same quantity
    across transcripts, and it must not drift from what the dashboard calls `ctx`."""
    return _ctx_of(usage) if isinstance(usage, dict) else 0


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
        "mtime": mtime, "size": 0, "_offset": 0, "_dev": None, "_ino": None, "_boundary": b"",
    }


def _fold(lines, state: dict, do_full: bool) -> None:
    """Fold JSONL text lines into ``state`` (mutated). Shared by full and incremental parses so
    their per-record semantics can't drift apart."""
    for line in lines:
        if "customTitle" not in line and '"assistant"' not in line and '"user"' not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        etype = ev.get("type")
        if etype == "custom-title" and ev.get("customTitle"):
            state["custom_title"] = ev["customTitle"]  # human-set; last one wins
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
                if state["first_user"] is None:
                    state["first_user"] = txt  # opening human prompt (stable identity; keep first)
                state["last_user"] = txt  # actual last user prompt (overwrite)
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
            state["last_model"] = msg["model"]
        ctx = _ctx_of(usage)  # last valid assistant usage wins (context = most recent turn)
        state["ctx"] = ctx
        if ctx > state["peak_ctx"]:
            state["peak_ctx"] = ctx
        if do_full:
            state["cum_input"] += _num(usage.get("input_tokens"))
            state["cum_output"] += _num(usage.get("output_tokens"))
            state["cum_cache"] += _num(usage.get("cache_read_input_tokens")) + _num(
                usage.get("cache_creation_input_tokens")
            )


def _seed(prev: dict | None) -> dict:
    if prev is None:
        return {"last_model": None, "ctx": 0, "peak_ctx": 0, "custom_title": None,
                "first_user": None, "last_user": None,
                "cum_input": 0, "cum_output": 0, "cum_cache": 0}
    return {"last_model": prev.get("model"), "ctx": prev.get("ctx", 0),
            "peak_ctx": prev.get("peak_ctx", 0), "custom_title": prev.get("custom_title") or None,
            "first_user": prev.get("initial_prompt") or None,
            "last_user": prev.get("last_prompt") or None, "cum_input": prev.get("cum_input", 0),
            "cum_output": prev.get("cum_output", 0), "cum_cache": prev.get("cum_cache", 0)}


def _parse(path: str, full: bool, prev: dict | None) -> dict:
    """Core fold. Resume from ``prev`` only when the file is provably the same, appended-to one;
    otherwise parse from 0. Reads in binary; a trailing record is folded as soon as it is complete
    JSON (with or without a closing newline) and left unconsumed only while genuinely mid-write."""
    try:  # stat once, up front — a transcript can rotate/vanish mid-read (hot file)
        st = os.stat(path)
    except OSError:
        return empty()
    size, mtime = st.st_size, st.st_mtime

    resume = (
        isinstance(prev, dict) and "_offset" in prev
        and prev.get("_dev") == st.st_dev and prev.get("_ino") == st.st_ino
        and prev.get("size", 0) <= size and prev["_offset"] <= size
    )
    start = prev["_offset"] if resume else 0
    # When resuming past 0, read one byte early to re-check the boundary the previous parse stopped
    # on: if it changed, the same inode was truncated+rewritten and we must NOT reuse the offset.
    read_at = start - 1 if resume and start > 0 else start
    try:
        with open(path, "rb") as fh:
            fh.seek(read_at)
            raw = fh.read()
    except OSError:
        return empty()  # vanished between stat and read
    if resume and start > 0:
        if raw[:1] == prev.get("_boundary"):
            raw = raw[1:]  # boundary intact — `raw` now starts at `start`
        else:
            resume, start = False, 0  # prefix changed — restart a full parse from 0
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
            except OSError:
                return empty()

    state = _seed(prev if resume else None)
    do_full = full and size <= MAX_FULL_PARSE

    nl = raw.rfind(b"\n")  # complete (newline-terminated) lines vs the trailing segment
    if nl >= 0:
        complete, tail, offset = raw[:nl + 1], raw[nl + 1:], start + nl + 1
    else:
        complete, tail, offset = b"", raw, start
    lines = complete.decode("utf-8", "ignore").splitlines()
    if tail:  # a trailing record with no newline is real once it is complete JSON — fold it then;
        tail_s = tail.decode("utf-8", "ignore")  # leave it only while still mid-write (invalid JSON)
        try:
            json.loads(tail_s)
        except ValueError:
            pass
        else:
            lines.append(tail_s)
            offset = start + len(raw)  # consumed to EOF (== size)
    _fold(lines, state, do_full)

    if not do_full:  # oversized transcript — mirror the full-parse contract (cum not tracked)
        state["cum_input"] = state["cum_output"] = state["cum_cache"] = 0
    # boundary = the last consumed byte (verified unchanged on the next resume). Keep the prior one
    # when this parse folded nothing new, so a quiet-but-touched file stays resumable.
    if offset > start:
        boundary = raw[offset - start - 1:offset - start]
    else:
        boundary = prev.get("_boundary", b"") if resume else b""

    return {
        "model": state["last_model"],
        "ctx": state["ctx"],
        "peak_ctx": state["peak_ctx"],
        "custom_title": " ".join(state["custom_title"].split())[:MAX_TEXT] if state.get("custom_title") else "",
        "initial_prompt": " ".join(state["first_user"].split())[:MAX_TEXT] if state["first_user"] else "",
        "last_prompt": " ".join(state["last_user"].split())[:MAX_TEXT] if state["last_user"] else "",
        "cum_input": state["cum_input"], "cum_output": state["cum_output"], "cum_cache": state["cum_cache"],
        "full": do_full, "mtime": mtime, "size": size,
        "_offset": offset, "_dev": st.st_dev, "_ino": st.st_ino, "_boundary": boundary,
    }


def parse(path: str, full: bool = True) -> dict:
    """Extract model / context / peak / cumulative tokens / title / last-prompt from a JSONL."""
    return _parse(path, full, None)


def parse_incremental(path: str, prev: dict, full: bool = True) -> dict:
    """Extend a prior ``parse`` result with only the bytes appended since — or fall back to a full
    parse if the file was rotated/rewritten (see module docstring). Equivalent to ``parse`` output."""
    return _parse(path, full, prev)
