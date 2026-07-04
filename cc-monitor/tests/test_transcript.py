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


def test_legit_angle_bracket_prompt_preserved(claude):
    # a real prompt that starts with '<' (pasted XML/HTML) must NOT be dropped as an envelope
    path = claude.transcript("s1", "/p", [
        user("<div>my actual question about this html</div>"),
        assistant("claude-opus-4-8", inp=100),
    ])
    assert transcript.parse(path)["last_prompt"].startswith("<div>my actual question")


def test_injected_origin_turn_skipped(claude):
    # a harness-injected turn (origin.kind != human) is not a prompt, even if its text is plain
    path = claude.transcript("s1", "/p", [
        user("real question", kind="human"),
        user("<task-notification>...</task-notification>", kind="task-notification"),
    ])
    assert transcript.parse(path)["last_prompt"] == "real question"


def test_malformed_origin_non_dict_no_crash(claude):
    # origin can be any JSON type in a bad line — a truthy non-dict must not crash .get()
    path = claude.transcript("s1", "/p", [
        {"type": "user", "message": {"content": "real"}, "origin": "not-a-dict"},
        assistant("claude-opus-4-8", inp=10),
    ])
    assert transcript.parse(path)["last_prompt"] == "real"


def test_empty_origin_kind_treated_as_human(claude):
    path = claude.transcript("s1", "/p", [
        {"type": "user", "message": {"content": "kept"}, "origin": {"kind": ""}},
    ])
    assert transcript.parse(path)["last_prompt"] == "kept"


def test_system_reminder_envelope_still_dropped(claude):
    path = claude.transcript("s1", "/p", [
        user("real"),
        user("<system-reminder>noise</system-reminder>"),
    ])
    assert transcript.parse(path)["last_prompt"] == "real"


def test_long_prompt_capped(claude):
    big = "x" * 5000
    path = claude.transcript("s1", "/p", [user(big), assistant("claude-opus-4-8", inp=10)])
    assert len(transcript.parse(path)["last_prompt"]) == transcript.MAX_TEXT


def test_missing_file_returns_empty():
    assert transcript.parse("/no/such/transcript.jsonl")["ctx"] == 0


def test_cumulative_tokens(claude):
    path = claude.transcript("s1", "/p", [
        assistant("claude-opus-4-8", inp=100, out=10),
        assistant("claude-opus-4-8", inp=200, out=20),
    ])
    info = transcript.parse(path)
    assert info["cum_input"] == 300
    assert info["cum_output"] == 30
