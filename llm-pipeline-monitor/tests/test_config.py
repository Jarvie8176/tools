"""Config plane — schema-gated, clamped, atomic. (Reused cc-monitor machinery, new SCHEMA.)"""
from __future__ import annotations

from llm_pipeline_monitor import config


def test_defaults(cfg_file):
    c = config.load()
    assert c["ctx_warn_pct"] == 50 and c["ctx_crit_pct"] == 80
    assert c["vram_warn_pct"] == 85 and c["tps_floor"] == 15


def test_save_and_reload(cfg_file):
    config.save({"ctx_warn_pct": 60})
    assert config.load()["ctx_warn_pct"] == 60


def test_out_of_range_clamped(cfg_file):
    c = config.save({"ctx_crit_pct": 999})
    assert c["ctx_crit_pct"] == 100  # clamped to max
    c = config.save({"ctx_warn_pct": -5})
    assert c["ctx_warn_pct"] == 0


def test_unknown_key_ignored(cfg_file):
    c = config.save({"bogus": 1, "tps_floor": 20})
    assert "bogus" not in c
    assert c["tps_floor"] == 20


def test_mistyped_value_falls_back(cfg_file):
    c = config.save({"tps_floor": "not-a-number"})
    assert c["tps_floor"] == 15  # default on coercion failure
