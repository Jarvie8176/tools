"""Runtime config: defaults / file-override / coercion / clamping / atomic save round-trip."""
import json

import pytest

from cc_monitor import config


@pytest.fixture(autouse=True)
def _clear_cache():
    config._cache[0] = None  # each test picks a fresh tmp path; never reuse a cached mtime
    yield
    config._cache[0] = None


def test_defaults_when_file_absent(tmp_path):
    assert config.load(str(tmp_path / "none.json")) == config.DEFAULTS


def test_file_overrides_and_coerces_and_drops_unknown(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"ctx_warn_pct": 33, "busy_idle_gap": "20", "bogus": 1}))
    cfg = config.load(str(p))
    assert cfg["ctx_warn_pct"] == 33
    assert cfg["busy_idle_gap"] == 20      # "20" coerced to int
    assert "bogus" not in cfg              # unknown key dropped


def test_out_of_range_is_clamped(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"ctx_warn_pct": 999, "busy_idle_gap": 0}))
    cfg = config.load(str(p))
    assert cfg["ctx_warn_pct"] == 100      # clamped to max
    assert cfg["busy_idle_gap"] == 1       # clamped to min


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{not valid json")
    assert config.load(str(p)) == config.DEFAULTS


def test_save_roundtrip_and_schema_gate(tmp_path):
    p = str(tmp_path / "cfg.json")
    eff = config.save({"ctx_crit_pct": 70, "evil": "rm -rf"}, p)
    assert eff["ctx_crit_pct"] == 70
    assert "evil" not in eff               # unknown key never written
    config._cache[0] = None
    assert config.load(p)["ctx_crit_pct"] == 70  # persisted across reload


def test_redact_default_is_safe_by_default(tmp_path):
    # safe-by-default: with no config file, prompt+title are masked (redact_default True)
    assert config.DEFAULTS["redact_default"] is True
    assert config.load(str(tmp_path / "none.json"))["redact_default"] is True


def test_save_coerces_bool(tmp_path):
    eff = config.save({"redact_default": "true"}, str(tmp_path / "cfg.json"))
    assert eff["redact_default"] is True


def test_cli_override_wins_over_file_and_is_not_persisted(tmp_path):
    # precedence: CLI override > config file > schema default; and the override never hits the file
    p = str(tmp_path / "cfg.json")
    config.save({"redact_default": True}, p)          # file says redact on
    config._cache[0] = None
    config.set_overrides(redact_default=False)        # per-invocation --no-redact
    assert config.load(p)["redact_default"] is False  # override wins over the file
    config.set_overrides()                            # clear (unset flag -> no-op)
    assert config.load(p)["redact_default"] is True   # falls back to the file value
    assert json.loads((tmp_path / "cfg.json").read_text())["redact_default"] is True  # file intact


def test_cache_is_atomic_holder_and_save_invalidates(tmp_path):
    # Fix A: cache slot holds a single (key, value) tuple set with one atomic subscript store —
    # never a two-field dict a concurrent reader could observe half-updated (new key + stale value).
    p = str(tmp_path / "cfg.json")
    config.load(p)
    assert config._cache[0] is None or isinstance(config._cache[0], tuple)
    config.save({"ctx_warn_pct": 11}, p)      # save() must invalidate then repopulate
    assert config.load(p)["ctx_warn_pct"] == 11


def test_save_drops_removed_or_unknown_keys(tmp_path):
    # a knob removed from SCHEMA (or any junk) must not be persisted forever across saves
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"ctx_warn_pct": 40, "active_gap": 900, "bogus": 1}))
    config.save({"ctx_crit_pct": 70}, str(p))
    on_disk = json.loads(p.read_text())
    assert "active_gap" not in on_disk and "bogus" not in on_disk
    assert on_disk["ctx_warn_pct"] == 40 and on_disk["ctx_crit_pct"] == 70


def test_schema_meta_shape():
    meta = config.schema_meta()
    assert set(meta) == set(config.SCHEMA)                       # exposes every knob, nothing extra
    for k, m in meta.items():
        default, lo, hi = config.SCHEMA[k]
        assert m["default"] == default
        if isinstance(default, bool):
            assert m["type"] == "bool" and "min" not in m        # bool has no range
        else:
            assert m["type"] == "int" and m["min"] == lo and m["max"] == hi


def test_schema_meta_flags_env_locked_knob(monkeypatch):
    monkeypatch.setenv("CC_MONITOR_BUSY_IDLE_GAP", "30")         # env override pins busy_idle_gap
    meta = config.schema_meta()
    assert meta["busy_idle_gap"]["env_locked"] == "CC_MONITOR_BUSY_IDLE_GAP"
    assert "env_locked" not in meta["ctx_warn_pct"]              # no env var for this knob


def test_schema_meta_no_env_lock_when_unset(monkeypatch):
    monkeypatch.delenv("CC_MONITOR_BUSY_IDLE_GAP", raising=False)
    assert "env_locked" not in config.schema_meta()["busy_idle_gap"]
