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
    assert info["initial_prompt"] == "first prompt"  # opening turn, kept as identity


def test_initial_prompt_is_first_human_turn(claude):
    # initial_prompt is the FIRST genuine human prompt and does not drift as the session continues;
    # envelopes/tool turns before it are skipped just like last_prompt.
    path = claude.transcript("s1", "/p", [
        user([{"type": "tool_result", "content": "x"}]),
        user("<system-reminder>noise</system-reminder>"),
        user("what is the plan"),
        assistant("claude-opus-4-8", inp=100),
        user("now do step 2"),
    ])
    info = transcript.parse(path)
    assert info["initial_prompt"] == "what is the plan"
    assert info["last_prompt"] == "now do step 2"


def test_initial_prompt_empty_when_no_human_turn(claude):
    path = claude.transcript("s1", "/p", [assistant("claude-opus-4-8", inp=10)])
    assert transcript.parse(path)["initial_prompt"] == ""


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


def test_message_null_or_non_dict_no_crash(claude):
    # `message` present-but-null (or a non-dict) must not crash the whole parse — the value is
    # skipped, and later valid rows still parse.
    path = claude.transcript("s1", "/p", [
        {"type": "user", "message": None},
        {"type": "user", "message": "not-a-dict"},
        user("real"),
        assistant("claude-opus-4-8", inp=10),
    ])
    info = transcript.parse(path)
    assert info["last_prompt"] == "real"
    assert info["model"] == "claude-opus-4-8"


def test_assistant_message_null_or_non_dict_no_crash(claude):
    # a null / non-dict assistant `message` is skipped, not fatal
    path = claude.transcript("s1", "/p", [
        {"type": "assistant", "message": None},
        {"type": "assistant", "message": "not-a-dict"},
        assistant("claude-opus-4-8", inp=100),
    ])
    info = transcript.parse(path)
    assert info["ctx"] == 100
    assert info["model"] == "claude-opus-4-8"


def test_usage_null_tokens_no_crash(claude):
    # a present-but-null token field must not crash the ctx / cumulative sum (None + int)
    path = claude.transcript("s1", "/p", [
        {"type": "assistant", "message": {"model": "claude-opus-4-8", "usage": {
            "input_tokens": None, "output_tokens": 5,
            "cache_read_input_tokens": None, "cache_creation_input_tokens": None,
        }}},
        assistant("claude-opus-4-8", inp=200),
    ])
    info = transcript.parse(path)
    assert info["ctx"] == 200          # last valid usage wins
    assert info["cum_output"] == 5     # null-token row still contributed its real output
    assert info["model"] == "claude-opus-4-8"


def test_usage_non_dict_no_crash(claude):
    # a non-dict `usage` (truthy but wrong shape) is skipped, not fatal
    path = claude.transcript("s1", "/p", [
        {"type": "assistant", "message": {"model": "claude-opus-4-8", "usage": "nope"}},
        assistant("claude-opus-4-8", inp=42),
    ])
    assert transcript.parse(path)["ctx"] == 42


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
