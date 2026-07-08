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


def test_explicit_max_context_not_clobbered_by_peak():
    # a deliberately-lowered ceiling must win even when a stale peak exceeds it
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "300000"}
    assert window.resolve_window(env, "claude-opus-4-8", 400_000) == (300_000, True)


def test_max_context_unicode_digit_no_crash():
    # str.isdigit() is True for '²' but int('²') raises — must fall back, not crash
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "²", "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve_window(env, "claude-opus-4-8", 0) == (1_000_000, True)


def test_max_context_zero_ignored():
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "0", "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve_window(env, "claude-opus-4-8", 10_000) == (1_000_000, True)


def test_read_model_env_excludes_default_headers(claude):
    claude.proc_alive(4243, {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]",
                             "ANTHROPIC_DEFAULT_HEADERS": "x-api-key: sk-secret"})
    env = window.read_model_env(4243)
    assert "ANTHROPIC_DEFAULT_HEADERS" not in env  # prefix match would have captured this
    assert env == {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}


# --- merge_model_env: settings.json env-block fallback beneath /proc environ ---

def test_merge_resume_worker_gets_1m_from_settings():
    # the bug: `claude --resume` proc env lacks the [1m] key (settings.json env is applied
    # internally, not in /proc) — the settings block must supply it so the window resolves to 1M.
    proc = {}  # readable but empty (resume worker's exec env)
    settings_env = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    merged = window.merge_model_env(proc, settings_env)
    assert window.resolve_window(merged, "claude-opus-4-8", 61_000) == (1_000_000, True)


def test_merge_proc_override_wins_over_settings():
    # a spawner-injected proc value is authoritative and wins per key over the settings default
    proc = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "300000"}
    settings_env = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    merged = window.merge_model_env(proc, settings_env)
    assert window.resolve_window(merged, "claude-opus-4-8", 10_000) == (300_000, True)


def test_merge_both_empty_is_none_preserving_uncertain():
    # no proc env AND no settings signal -> None -> resolve_window keeps its '?' (uncertain) path
    assert window.merge_model_env(None, {}) is None
    assert window.merge_model_env(None, None) is None
    assert window.resolve_window(window.merge_model_env(None, {}), "claude-opus-4-8", 100_000) \
        == (200_000, False)


def test_merge_proc_unreadable_falls_back_to_settings():
    # /proc unreadable (None) but settings has [1m] -> still resolvable with certainty
    merged = window.merge_model_env(None, {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"})
    assert window.resolve_window(merged, "claude-opus-4-8", 50_000) == (1_000_000, True)


def test_merge_readable_empty_proc_no_settings_stays_certain_200k():
    # observed the env, found no override, and no global default either -> 200k is a certain answer
    merged = window.merge_model_env({}, {})
    assert merged == {}  # dict, not None: we DID read the env
    assert window.resolve_window(merged, "claude-opus-4-8", 150_000) == (200_000, True)
