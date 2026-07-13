"""Hermetic fixtures — all data synthetic (no real fleet hosts/addrs/model paths)."""
from __future__ import annotations

import pytest

from llm_pipeline_monitor import config


@pytest.fixture(autouse=True)
def _reset_config_state():
    """Per-invocation config globals must not leak across tests."""
    config._overrides = {}
    config._cache[0] = None
    yield
    config._overrides = {}
    config._cache[0] = None


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """Point the config plane at a temp file."""
    p = tmp_path / "config.json"
    monkeypatch.setattr("llm_pipeline_monitor.paths.CONFIG_FILE", str(p))
    return str(p)


def sample(name, value, **labels):
    """A Prometheus /api/v1/query result entry."""
    metric = {"__name__": name, **labels}
    return {"metric": metric, "value": [0, str(value)]}
