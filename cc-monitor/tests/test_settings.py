from cc_monitor import settings


def test_effort_level_read(claude):
    claude.settings({"effortLevel": "high", "model": "claude-opus-4-8[1m]"})
    assert settings.effort_level() == "high"


def test_effort_level_absent_file_is_none(claude):
    # no settings.json written -> None (UI shows '?'), never a crash
    assert settings.effort_level() is None


def test_effort_level_missing_key_is_none(claude):
    claude.settings({"model": "claude-opus-4-8"})  # no effortLevel
    assert settings.effort_level() is None


def test_effort_level_only_returns_the_scalar_not_the_file(claude):
    # settings.json also holds env/secrets; the reader must surface ONLY effortLevel
    claude.settings({"effortLevel": "medium", "env": {"SECRET": "leak-me"}})
    assert settings.effort_level() == "medium"


def test_effort_level_garbage_value_capped(claude):
    claude.settings({"effortLevel": "x" * 500})
    assert len(settings.effort_level()) == settings._MAX


def test_effort_level_non_string_is_none(claude):
    claude.settings({"effortLevel": 3})
    assert settings.effort_level() is None


def test_effort_level_malformed_json_is_none(claude):
    with open(claude.settings_file, "w") as fh:
        fh.write("{not json")
    assert settings.effort_level() is None


def test_model_env_reads_window_keys_from_env_block(claude):
    claude.settings({"effortLevel": "high", "env": {
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]",
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000",
        "PATH": "/usr/bin",              # not a window key -> filtered out
        "ANTHROPIC_API_KEY": "sk-secret",  # never surfaced
    }})
    env = settings.model_env()
    assert env == {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]",
                   "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "500000"}


def test_model_env_no_env_block_is_empty(claude):
    claude.settings({"effortLevel": "high"})  # no env block
    assert settings.model_env() == {}


def test_model_env_absent_file_is_empty(claude):
    assert settings.model_env() == {}
