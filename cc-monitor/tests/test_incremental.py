"""Incremental parse: extending a prior parse with only the appended bytes must be identical to a
full re-parse, and must fall back to a full parse when the append-only invariant breaks."""
import time

from cc_monitor import collect, transcript

from .conftest import assistant, custom_title, user

# public fields callers rely on — `_offset` is an internal cursor and compared separately
_FIELDS = ("model", "ctx", "peak_ctx", "custom_title", "initial_prompt", "last_prompt",
           "cum_input", "cum_output", "cum_cache", "full", "size")


def _same(a: dict, b: dict):
    for k in _FIELDS:
        assert a[k] == b[k], f"field {k}: incremental={a[k]!r} full={b[k]!r}"


def test_incremental_equals_full_after_append(claude):
    path = claude.transcript("s1", "/p", [
        custom_title("Epic work"),
        user("first prompt"),
        assistant("claude-opus-4-8", inp=100, out=10),
    ])
    prev = transcript.parse(path)
    claude.append(path, [
        user("second prompt"),
        assistant("claude-sonnet-5", inp=250, out=20),
    ])
    inc = transcript.parse_incremental(path, prev)
    full = transcript.parse(path)
    _same(inc, full)
    # and it actually folded the new turns
    assert inc["last_prompt"] == "second prompt"
    assert inc["initial_prompt"] == "first prompt"  # stable identity, not overwritten
    assert inc["model"] == "claude-sonnet-5"
    assert inc["ctx"] == 250
    assert inc["cum_input"] == 350 and inc["cum_output"] == 30
    assert inc["_offset"] == full["_offset"] == prev["size"] + (full["size"] - prev["size"])


def test_incremental_preserves_peak_high_water(claude):
    # the peak is the high-water mark; a later, smaller turn must not lower it across an append
    path = claude.transcript("s1", "/p", [assistant("claude-opus-4-8", inp=300_000)])
    prev = transcript.parse(path)
    assert prev["peak_ctx"] == 300_000
    claude.append(path, [assistant("claude-opus-4-8", inp=120_000)])
    inc = transcript.parse_incremental(path, prev)
    assert inc["ctx"] == 120_000       # current = latest turn
    assert inc["peak_ctx"] == 300_000  # peak survives from the pre-append accumulator
    _same(inc, transcript.parse(path))


def test_incremental_no_new_bytes_is_noop(claude):
    path = claude.transcript("s1", "/p", [assistant("claude-opus-4-8", inp=100)])
    prev = transcript.parse(path)
    inc = transcript.parse_incremental(path, prev)  # nothing appended
    _same(inc, prev)
    assert inc["_offset"] == prev["_offset"]


def test_incremental_falls_back_on_shrink(claude):
    # a rotated/truncated transcript (smaller than the prior parse) can't be resumed — the offset
    # would point past unrelated bytes — so it must full-parse the new content from 0.
    path = claude.transcript("s1", "/p", [
        user("old A"), user("old B"),
        assistant("claude-opus-4-8", inp=500_000),
    ])
    prev = transcript.parse(path)
    # rewrite (overwrite) with a shorter, unrelated transcript
    claude.transcript("s1", "/p", [assistant("claude-sonnet-5", inp=42)])
    inc = transcript.parse_incremental(path, prev)
    full = transcript.parse(path)
    _same(inc, full)
    assert inc["peak_ctx"] == 42          # NOT the stale 500_000 from the old accumulator
    assert inc["model"] == "claude-sonnet-5"
    assert inc["last_prompt"] == ""       # old prompts gone, not carried over


def test_incremental_leaves_trailing_partial_line(claude):
    # a mid-write transcript can end without a trailing newline; the partial line must be left
    # unconsumed (offset not advanced past it) and folded once its newline lands.
    path = claude.transcript("s1", "/p", [assistant("claude-opus-4-8", inp=100)])
    prev = transcript.parse(path)
    claude.append(path, [assistant("claude-opus-4-8", inp=999)], newline=False)  # partial
    mid = transcript.parse_incremental(path, prev)
    assert mid["ctx"] == 100                    # partial turn not yet folded
    assert mid["_offset"] == prev["_offset"]    # cursor held at the last complete line
    # now the newline arrives (the writer finishes the line)
    with open(path, "a") as fh:
        fh.write("\n")
    done = transcript.parse_incremental(path, mid)
    assert done["ctx"] == 999                   # now folded
    _same(done, transcript.parse(path))


def test_incremental_full_flag_and_cum_capped_when_no_prev(claude):
    # parse_incremental with prev=None (or a prev lacking _offset) behaves as a full parse
    path = claude.transcript("s1", "/p", [assistant("claude-opus-4-8", inp=100, out=5)])
    assert transcript.parse_incremental(path, {}) == transcript.parse(path)
    assert transcript.parse_incremental(path, None) == transcript.parse(path)


def test_collect_uses_incremental_on_growth(claude):
    # end-to-end: a growing transcript across two collects yields rows identical to a full parse,
    # and the internal _offset cursor never leaks into a dashboard row.
    claude.registry(1, "u", "/home/x/p")
    claude.proc_alive(1, {})
    path = claude.transcript("u", "/home/x/p", [user("hi"), assistant("claude-opus-4-8", inp=100)])
    collect._PARSE_CACHE.clear()
    collect.collect(now=time.time())
    claude.append(path, [user("more"), assistant("claude-opus-4-8", inp=250, out=7)])
    row = collect.collect(now=time.time())["rows"][0]
    assert "_offset" not in row               # internal cursor stripped from the row/API
    assert row["ctx"] == 250 and row["last_prompt"] == "more"
    assert row["cum_output"] == 7
    # matches a from-scratch full parse of the grown file
    fresh = transcript.parse(path)
    for k in ("ctx", "peak_ctx", "cum_input", "cum_output", "last_prompt", "initial_prompt"):
        assert row[k] == fresh[k]


def test_collect_incremental_folds_only_appended_bytes(claude, monkeypatch):
    # prove the cache-miss path resumes from the prior offset rather than re-scanning from 0: after
    # the first collect, tamper the cached accumulator; an incremental re-parse of ONLY the appended
    # tail keeps the tampered peak (a full re-scan from 0 would recompute and erase it).
    claude.registry(1, "u", "/home/x/p")
    claude.proc_alive(1, {})
    path = claude.transcript("u", "/home/x/p", [assistant("claude-opus-4-8", inp=100)])
    collect._PARSE_CACHE.clear()
    collect.collect(now=time.time())
    cached = collect._PARSE_CACHE[path][1]
    cached["peak_ctx"] = 777_777  # sentinel only reachable if we resume from this accumulator
    claude.append(path, [assistant("claude-opus-4-8", inp=50)])
    row = collect.collect(now=time.time())["rows"][0]
    assert row["peak_ctx"] == 777_777  # resumed from the offset, did not re-scan the whole file
