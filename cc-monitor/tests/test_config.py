"""Runtime config: defaults / file-override / coercion / clamping / atomic save round-trip."""
import json

import pytest

from cc_monitor import config


@pytest.fixture(autouse=True)
def _clear_cache():
    config._cache["key"] = None  # each test picks a fresh tmp path; never reuse a cached mtime
    yield
    config._cache["key"] = None


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
    config._cache["key"] = None
    assert config.load(p)["ctx_crit_pct"] == 70  # persisted across reload


def test_save_coerces_bool(tmp_path):
    eff = config.save({"redact_default": "true"}, str(tmp_path / "cfg.json"))
    assert eff["redact_default"] is True
