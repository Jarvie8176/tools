from cc_monitor import window


def test_env_1m_default_is_certain_1m():
    env = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve_window(env, "claude-opus-4-8", 50_000) == (1_000_000, True)


def test_env_no_1m_is_certain_200k():
    # env readable, no [1m] default -> genuinely 200k even though model is opus
    env = {}
    assert window.resolve_window(env, "claude-opus-4-8", 150_000) == (200_000, True)


def test_peak_lower_bound_overrides_env_guess():
    # env says 200k but usage already exceeds it -> must be 1M (worker got [1m] via CLI/other)
    env = {}
    assert window.resolve_window(env, "claude-opus-4-8", 369_000) == (1_000_000, True)


def test_max_context_override_wins():
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000"}
    assert window.resolve_window(env, "claude-opus-4-8", 10_000) == (500_000, True)


def test_env_unreadable_low_peak_is_uncertain():
    # the one truly-unknowable case: no env, never crossed 200k -> flagged
    assert window.resolve_window(None, "claude-opus-4-8", 100_000) == (200_000, False)


def test_env_unreadable_high_peak_is_certain_1m():
    assert window.resolve_window(None, "claude-opus-4-8", 800_000) == (1_000_000, True)


def test_sonnet_defaults_200k():
    assert window.resolve_window({}, "claude-sonnet-5", 50_000) == (200_000, True)


def test_read_model_env_masks_non_model_keys(claude):
    claude.proc_alive(4242, {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]",
                             "ANTHROPIC_API_KEY": "sk-secret-should-not-surface"})
    env = window.read_model_env(4242)
    assert env == {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert "ANTHROPIC_API_KEY" not in env


def test_read_model_env_missing_proc_returns_none(claude):
    assert window.read_model_env(999999) is None
