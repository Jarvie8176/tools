"""Parse a Claude Code transcript JSONL into the fields the dashboard needs.

Context size is derived from the input-side of the last assistant ``usage``
(``input + cache_read + cache_creation``) — this is unaffected by the known ``output_tokens``
undercount (anthropics/claude-code#27361). TITLE (human ``custom-title``) and LAST-PROMPT (the
actual last user turn) are returned separately: the last prompt drifts and is not an identity.
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


def _ctx_of(usage: dict) -> int:
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def empty(mtime: float = 0.0) -> dict:
    return {
        "model": None, "ctx": 0, "peak_ctx": 0, "custom_title": "", "last_prompt": "",
        "cum_input": 0, "cum_output": 0, "cum_cache": 0, "full": False,
        "mtime": mtime, "size": 0,
    }


def parse(path: str, full: bool = True) -> dict:
    """Extract model / context / peak / cumulative tokens / title / last-prompt from a JSONL."""
    last_model = last_usage = None
    custom_title = last_user = None
    peak_ctx = cum_input = cum_output = cum_cache = 0
    try:  # stat once, up front — a transcript can rotate/vanish mid-read (hot file)
        size = os.path.getsize(path)
        mtime = os.path.getmtime(path)
    except OSError:
        return empty()
    do_full = full and size <= MAX_FULL_PARSE
    try:
        with open(path, errors="ignore") as fh:
            for line in fh:
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
                    txt = user_text(ev.get("message", {}).get("content"))
                    if txt:
                        last_user = txt  # actual last user prompt (overwrite)
                    continue
                if etype != "assistant":
                    continue
                msg = ev.get("message", {})
                usage = msg.get("usage")
                if not usage:
                    continue
                if msg.get("model") and msg["model"] != "<synthetic>":
                    last_model = msg["model"]
                last_usage = usage
                turn_ctx = _ctx_of(usage)
                if turn_ctx > peak_ctx:
                    peak_ctx = turn_ctx
                if do_full:
                    cum_input += usage.get("input_tokens", 0)
                    cum_output += usage.get("output_tokens", 0)
                    cum_cache += usage.get("cache_read_input_tokens", 0) + usage.get(
                        "cache_creation_input_tokens", 0
                    )
    except OSError:
        pass
    return {
        "model": last_model,
        "ctx": _ctx_of(last_usage) if last_usage else 0,
        "peak_ctx": peak_ctx,
        "custom_title": " ".join(custom_title.split())[:MAX_TEXT] if custom_title else "",
        "last_prompt": " ".join(last_user.split())[:MAX_TEXT] if last_user else "",
        "cum_input": cum_input, "cum_output": cum_output, "cum_cache": cum_cache,
        "full": do_full, "mtime": mtime, "size": size,
    }
