from cc_monitor import transcript

from .conftest import assistant, custom_title, user


def test_parse_context_is_input_side(claude):
    path = claude.transcript("s1", "/p", [
        assistant("claude-opus-4-8", inp=1000, cache_read=2000, cache_creation=500, out=9999),
    ])
    info = transcript.parse(path)
    # ctx = input + cache_read + cache_creation (NOT output — #27361 safe)
    assert info["ctx"] == 3500
    assert info["model"] == "claude-opus-4-8"


def test_peak_is_high_water_mark(claude):
    path = claude.transcript("s1", "/p", [
        assistant("claude-opus-4-8", inp=300_000),
        assistant("claude-opus-4-8", inp=120_000),  # current lower than peak
    ])
    info = transcript.parse(path)
    assert info["ctx"] == 120_000
    assert info["peak_ctx"] == 300_000


def test_synthetic_model_ignored(claude):
    path = claude.transcript("s1", "/p", [
        assistant("claude-opus-4-8", inp=100),
        assistant("<synthetic>", inp=50),
    ])
    assert transcript.parse(path)["model"] == "claude-opus-4-8"


def test_custom_title_and_last_prompt_separate(claude):
    path = claude.transcript("s1", "/p", [
        custom_title("Photo pipeline migration"),
        user("first prompt"),
        assistant("claude-opus-4-8", inp=100),
        user("go P2"),
    ])
    info = transcript.parse(path)
    assert info["custom_title"] == "Photo pipeline migration"
    assert info["last_prompt"] == "go P2"  # last, not first


def test_last_prompt_skips_tool_envelopes(claude):
    path = claude.transcript("s1", "/p", [
        user("real question"),
        user([{"type": "tool_result", "content": "x"}]),
        user("<system-reminder>noise</system-reminder>"),
    ])
    # only the genuine text prompt survives
    assert transcript.parse(path)["last_prompt"] == "real question"


def test_cumulative_tokens(claude):
    path = claude.transcript("s1", "/p", [
        assistant("claude-opus-4-8", inp=100, out=10),
        assistant("claude-opus-4-8", inp=200, out=20),
    ])
    info = transcript.parse(path)
    assert info["cum_input"] == 300
    assert info["cum_output"] == 30
