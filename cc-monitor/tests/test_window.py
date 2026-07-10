from cc_monitor import window


def test_env_1m_default_is_certain_1m():
    env = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve_window(env, "claude-opus-4-8", 50_000) == (1_000_000, True)


def test_env_readable_but_empty_is_uncertain_200k():
    # A readable env with no model keys is NOT evidence of 200k: Claude Code appends [1m] at
    # runtime from an account-level predicate and needs no env at all. Value yes, certainty no.
    assert window.resolve_window({}, "claude-opus-4-8", 150_000) == (200_000, False)


def test_peak_lower_bound_overrides_env_guess():
    # env says 200k but usage already exceeds it -> must be 1M (worker got [1m] via CLI/other)
    env = {}
    assert window.resolve_window(env, "claude-opus-4-8", 369_000) == (1_000_000, True)


def test_max_context_ignored_for_first_party_model_without_disable_compact():
    # Claude Code only honours the ceiling when compaction is off, or for a non-`claude-*` model.
    # Reporting it unconditionally showed a ceiling the running session was never subject to.
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000"}
    assert window.resolve_window(env, "claude-opus-4-8", 10_000) == (200_000, False)


def test_max_context_honoured_with_disable_compact():
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000", "DISABLE_COMPACT": "1"}
    assert window.resolve_window(env, "claude-opus-4-8", 10_000) == (500_000, True)


def test_max_context_honoured_for_third_party_model():
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000"}
    assert window.resolve_window(env, "my-org/custom-llm", 10_000) == (500_000, True)


def test_env_unreadable_low_peak_is_uncertain():
    # the one truly-unknowable case: no env, never crossed 200k -> flagged
    assert window.resolve_window(None, "claude-opus-4-8", 100_000) == (200_000, False)


def test_env_unreadable_high_peak_is_certain_1m():
    assert window.resolve_window(None, "claude-opus-4-8", 800_000) == (1_000_000, True)


def test_sonnet_no_evidence_is_uncertain():
    assert window.resolve_window({}, "claude-sonnet-5", 50_000) == (200_000, False)


def test_fable_family_recognised():
    # `fable` was missing from the family list, so ANTHROPIC_DEFAULT_FABLE_MODEL never resolved and
    # every Fable session pinned to the baseline window.
    assert window.family("claude-fable-5") == "FABLE"
    env = {"ANTHROPIC_DEFAULT_FABLE_MODEL": "claude-fable-5[1m]"}
    assert window.resolve_window(env, "claude-fable-5", 50_000) == (1_000_000, True)


def test_disable_1m_kill_switch_is_certain_200k():
    env = {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve_window(env, "claude-opus-4-8", 50_000) == (200_000, True)


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
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "300000", "DISABLE_COMPACT": "true"}
    assert window.resolve_window(env, "claude-opus-4-8", 400_000) == (300_000, True)


def test_max_context_unicode_digit_no_crash():
    # str.isdigit() is True for '²' but int('²') raises — must fall back, not crash
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "²", "DISABLE_COMPACT": "1",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve_window(env, "claude-opus-4-8", 0) == (1_000_000, True)


def test_max_context_zero_ignored():
    env = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "0", "DISABLE_COMPACT": "1",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
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
    assert window.resolve({}, _S1M, "claude-opus-4-8", 61_000, True) == (1_000_000, True, False)


def test_resolve_settings_untrusted_is_uncertain():
    # settings changed after the worker started (untrusted): supply the 1M VALUE but flag '?'.
    assert window.resolve({}, _S1M, "claude-opus-4-8", 61_000, False) == (1_000_000, False, False)


def test_resolve_untrusted_but_peak_proves_1m():
    # even untrusted, usage above baseline is hard proof -> certain 1M
    assert window.resolve({}, _S1M, "claude-opus-4-8", 400_000, False) == (1_000_000, True, False)


def test_resolve_proc_unreadable_ignores_settings():
    # /proc unreadable (None): never fabricate certainty from global settings for an unseen env.
    assert window.resolve(None, _S1M, "claude-opus-4-8", 50_000, True) == (200_000, False, False)
    # peak still proves it when high
    assert window.resolve(None, _S1M, "claude-opus-4-8", 800_000, True) == (1_000_000, True, False)


def test_resolve_proc_override_wins_over_settings():
    # a spawner [1m] in /proc is observed evidence -> certain 1M regardless of settings/trust
    proc = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]"}
    assert window.resolve(proc, {}, "claude-opus-4-8", 10_000, False) == (1_000_000, True, False)


def test_resolve_no_evidence_anywhere_is_uncertain():
    # observed env, no override, no settings default, nothing declared -> unknown, flagged '?'.
    # This is the default install, and the case that used to render a confident (wrong) 200k.
    assert window.resolve({}, {}, "claude-opus-4-8", 150_000, False) == (200_000, False, False)


def test_resolve_settings_max_context_untrusted_uncertain():
    # a settings MAX_CONTEXT ceiling (>baseline) is provisional too -> value yes, certainty gated
    s = {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000", "DISABLE_COMPACT": "1"}
    assert window.resolve({}, s, "claude-opus-4-8", 10_000, False) == (500_000, False, False)
    assert window.resolve({}, s, "claude-opus-4-8", 10_000, True) == (500_000, True, False)


# --- mechanized derivation: a model launch must not require a code change ---


def test_family_derived_not_enumerated():
    # every id shape Claude Code emits, plus a family that does not exist yet
    assert window.family("claude-opus-4-8") == "OPUS"
    assert window.family("claude-fable-5[1m]") == "FABLE"
    assert window.family("claude-haiku-4-5-20251001") == "HAIKU"
    assert window.family("claude-3-5-sonnet-20241022") == "SONNET"  # legacy date-first id
    assert window.family("us.anthropic.claude-opus-4-8-v1:0") == "OPUS"  # bedrock prefix
    assert window.family("claude-mythos-preview") == "MYTHOS"  # unshipped family, no code change
    assert window.family("my-org/custom-llm") is None
    assert window.family("") is None


def test_unknown_family_env_default_is_honoured():
    # a family nobody has heard of yet still resolves from its own ANTHROPIC_DEFAULT_*_MODEL
    env = {"ANTHROPIC_DEFAULT_MYTHOS_MODEL": "claude-mythos-preview[1m]"}
    assert window.resolve_window(env, "claude-mythos-preview", 0) == (1_000_000, True)


def test_suffix_magnitude_parsed_not_matched():
    assert window.suffix_window("claude-opus-4-8[1m]") == 1_000_000
    assert window.suffix_window("claude-opus-9-0[2m]") == 2_000_000  # future tier, no code change
    assert window.suffix_window("claude-opus-4-8") is None


def test_two_m_suffix_resolves_to_two_m():
    env = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-9-0[2m]"}
    assert window.resolve_window(env, "claude-opus-9-0", 0) == (2_000_000, True)


def test_model_env_key_predicate_excludes_siblings():
    assert window.is_model_env_key("ANTHROPIC_DEFAULT_MYTHOS_MODEL")  # unknown family, allowed
    assert not window.is_model_env_key("ANTHROPIC_DEFAULT_OPUS_MODEL_NAME")
    assert not window.is_model_env_key("ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES")
    assert not window.is_model_env_key("ANTHROPIC_DEFAULT_HEADERS")
    assert not window.is_model_env_key("ANTHROPIC_API_KEY")


def test_peak_promotes_to_smallest_known_window():
    # a 2M window declared for some model means a 1.4M peak promotes to 2M, not a hard-coded 1M
    got = window.resolve({}, {}, "claude-sonnet-5", 1_400_000, False, known={200_000, 2_000_000})
    assert got == (2_000_000, True, False)


# --- declaration layer ---


def test_declared_window_is_certain():
    assert window.resolve({}, {}, "claude-opus-4-8", 10_000, False,
                          declared=1_000_000) == (1_000_000, True, False)


def test_undeclared_model_is_flagged_not_guessed():
    assert window.resolve({}, {}, "claude-newthing-1", 10_000, False) == (200_000, False, False)


def test_peak_above_declaration_promotes_and_conflicts():
    # usage cannot exceed the real window: the declaration is provably stale, and must not be
    # corrected in silence.
    got = window.resolve({}, {}, "claude-opus-4-8", 400_000, False,
                         declared=200_000, known={200_000, 1_000_000})
    assert got == (1_000_000, True, True)


def test_env_override_of_declaration_is_not_a_conflict():
    # the kill switch is per-worker; a per-model declaration cannot know about it. Overriding is
    # the override doing its job, not evidence that the map is wrong.
    env = {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}
    assert window.resolve(env, {}, "claude-opus-4-8", 0, False,
                          declared=1_000_000) == (200_000, True, False)


def test_declaration_outranks_settings_env_fallback():
    assert window.resolve({}, _S1M, "claude-opus-4-8", 0, False,
                          declared=200_000) == (200_000, True, False)


def test_peak_beyond_every_known_window_is_flagged_not_guessed():
    # usage above every candidate proves the window is at least the peak, but not what it IS.
    # Reporting a hard-coded 1M here would be a window smaller than the observed usage.
    assert window.resolve_window({}, "claude-opus-4-8", 1_500_000) == (1_500_000, False)
