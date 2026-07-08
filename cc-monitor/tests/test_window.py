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


# --- resolve(): settings.json env-block fallback with certainty provenance ---

_S1M = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}


def test_resolve_resume_worker_trusted_is_certain_1m():
    # `claude --resume` proc env lacks [1m] (settings applied internally). With the worker started
    # under the current settings (trusted), the fallback resolves to 1M with certainty.
    assert window.resolve({}, _S1M, "claude-opus-4-8", 61_000, True) == (1_000_000, True)


def test_resolve_settings_untrusted_is_uncertain():
    # settings changed after the worker started (untrusted): supply the 1M VALUE but flag '?'.
    assert window.resolve({}, _S1M, "claude-opus-4-8", 61_000, False) == (1_000_000, False)


def test_resolve_untrusted_but_peak_proves_1m():
    # even untrusted, usage above baseline is hard proof -> certain 1M
    assert window.resolve({}, _S1M, "claude-opus-4-8", 400_000, False) == (1_000_000, True)


def test_resolve_proc_unreadable_ignores_settings():
    # /proc unreadable (None): never fabricate certainty from global settings for an unseen env.
    assert window.resolve(None, _S1M, "claude-opus-4-8", 50_000, True) == (200_000, False)
    # peak still proves it when high
    assert window.resolve(None, _S1M, "claude-opus-4-8", 800_000, True) == (1_000_000, True)


def test_resolve_proc_override_wins_over_settings():
    # a spawner [1m] in /proc is observed evidence -> certain 1M regardless of settings/trust
    proc = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve(proc, {}, "claude-opus-4-8", 10_000, False) == (1_000_000, True)


def test_resolve_no_settings_readable_proc_is_certain_200k():
    # observed env, no override, no settings default -> 200k certain (unchanged baseline behaviour)
    assert window.resolve({}, {}, "claude-opus-4-8", 150_000, False) == (200_000, True)


def test_resolve_settings_max_context_untrusted_uncertain():
    # a settings MAX_CONTEXT ceiling (>baseline) is provisional too -> value yes, certainty gated
    s = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000"}
    assert window.resolve({}, s, "claude-opus-4-8", 10_000, False) == (500_000, False)
    assert window.resolve({}, s, "claude-opus-4-8", 10_000, True) == (500_000, True)
