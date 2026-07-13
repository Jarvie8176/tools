"""prom adapter — assembles per-endpoint rows from Prometheus series. All data synthetic."""
from __future__ import annotations

import pytest

from llm_pipeline_monitor import prom
from tests.conftest import sample

GGUF = "/models/synthetic-7b.gguf"


def _series_one_host():
    h = {"host": "node-a"}
    return [
        sample("llm_endpoint_up", 1, **h),
        sample("llm_endpoint_resident_model", 1, served_id=GGUF, model_key="syn-7b", **h),
        sample("llm_endpoint_tokens_per_second", 800, phase="prompt", **h),
        sample("llm_endpoint_tokens_per_second", 42, phase="generation", **h),
        sample("llm_endpoint_active_requests", 0, **h),
        sample("llm_endpoint_deferred_requests", 0, **h),
        sample("llm_endpoint_ctx_used_tokens", 8000, **h),
        sample("llm_endpoint_ctx_used_tokens_peak", 16000, **h),
        sample("llm_endpoint_ctx_effective_tokens", 32768, **h),
        sample("llm_endpoint_kv_cache_usage_ratio", 0.25, **h),
        sample("llm_host_gpu_utilization_ratio", 0.5, **h),
        sample("llm_host_gpu_vram_used_bytes", 9_000_000_000, **h),
        sample("llm_host_gpu_vram_total_bytes", 24_000_000_000, **h),
        # two swap transitions -> total 3
        sample("llm_endpoint_swap_total", 2, **{**h, "from": "a", "to": "b"}),
        sample("llm_endpoint_swap_total", 1, **{**h, "from": "b", "to": "a"}),
    ]


def test_collect_assembles_row(monkeypatch):
    monkeypatch.setattr(prom, "_query", lambda *a, **k: _series_one_host())
    d = prom.collect()
    assert d["ok"] is True and d["error"] is None
    assert len(d["rows"]) == 1
    r = d["rows"][0]
    assert r["host"] == "node-a"
    assert r["up"] == 1
    # served_id is the real gguf (drift-proof), model_key is the routing key
    assert r["served_id"] == GGUF
    assert r["model_key"] == "syn-7b"
    assert r["tok_s_prompt"] == 800 and r["tok_s_gen"] == 42
    # ctx_pct uses the PEAK (16000/32768 ~ 48.8), not the instantaneous used
    assert r["ctx_used"] == 8000 and r["ctx_peak"] == 16000 and r["ctx_effective"] == 32768
    assert r["ctx_pct"] == pytest.approx(48.8, abs=0.1)
    assert r["vram_pct"] == pytest.approx(37.5, abs=0.1)
    assert r["swap_total"] == 3  # summed across (from,to) transitions
    assert r["kv_ratio"] == 0.25


def test_collect_buckets_by_host(monkeypatch):
    series = [
        sample("llm_endpoint_up", 1, host="node-a"),
        sample("llm_endpoint_up", 0, host="node-b"),
        sample("llm_endpoint_resident_model", 1, served_id=GGUF, model_key="syn", host="node-a"),
    ]
    monkeypatch.setattr(prom, "_query", lambda *a, **k: series)
    rows = {r["host"]: r for r in prom.collect()["rows"]}
    assert rows["node-a"]["up"] == 1 and rows["node-b"]["up"] == 0
    assert rows["node-a"]["served_id"] == GGUF


def test_series_without_host_skipped(monkeypatch):
    monkeypatch.setattr(prom, "_query", lambda *a, **k: [sample("llm_endpoint_up", 1)])  # no host
    assert prom.collect()["rows"] == []


def test_upstream_failure_is_soft(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(prom, "_query", boom)
    d = prom.collect()
    assert d["ok"] is False
    assert d["rows"] == []
    assert "connection refused" in d["error"]


def test_non_finite_values_sanitized(monkeypatch):
    # Prometheus emits "NaN"/"+Inf"/"-Inf"; they must become None (not crash int(), not emit
    # invalid JSON). Cover both an int-typed field (would crash int()) and float-typed fields.
    h = {"host": "node-a"}
    series = [
        sample("llm_endpoint_up", 1, **h),
        sample("llm_endpoint_ctx_used_tokens", "NaN", **h),        # int field
        sample("llm_endpoint_ctx_effective_tokens", "+Inf", **h),  # int field
        sample("llm_endpoint_tokens_per_second", "NaN", phase="generation", **h),  # float field
        sample("llm_host_gpu_utilization_ratio", "-Inf", **h),
    ]
    monkeypatch.setattr(prom, "_query", lambda *a, **k: series)
    d = prom.collect()  # must not raise
    assert d["ok"] is True
    r = d["rows"][0]
    assert r["ctx_used"] is None and r["ctx_effective"] is None
    assert r["tok_s_gen"] is None and r["gpu_util"] is None
    # and the serialized payload is spec-valid JSON (no NaN/Infinity tokens)
    from llm_pipeline_monitor.stream import serialize
    import json
    body = serialize(d).decode()
    assert "NaN" not in body and "Infinity" not in body
    json.loads(body)  # strict parse succeeds


def test_resident_model_latest_timestamp_wins(monkeypatch):
    # After a swap the OLD resident_model series is still returned within lookback-delta with
    # value 1; the row must show the LATEST-timestamp sample, not an order-dependent stale one.
    def rm(served, ts):
        return {"metric": {"__name__": "llm_endpoint_resident_model", "host": "node-a",
                            "served_id": served, "model_key": served.split("/")[-1]},
                "value": [ts, "1"]}
    for order in ([rm("/models/old.gguf", 100), rm("/models/new.gguf", 200)],
                  [rm("/models/new.gguf", 200), rm("/models/old.gguf", 100)]):
        monkeypatch.setattr(prom, "_query", lambda *a, _o=order, **k: _o)
        r = prom.collect()["rows"][0]
        assert r["served_id"] == "/models/new.gguf", f"stale gguf won for order {order}"


def test_scheme_rejected(monkeypatch):
    monkeypatch.setattr("llm_pipeline_monitor.paths.PROM_URL", "file:///etc/passwd")
    called = []
    monkeypatch.setattr(prom, "_query", lambda *a, **k: called.append(1) or [])
    d = prom.collect()
    assert d["ok"] is False and not called  # never touched _query for a non-http scheme


def test_ctx_pct_clamped(monkeypatch):
    h = {"host": "node-a"}
    series = [
        sample("llm_endpoint_up", 1, **h),
        sample("llm_endpoint_ctx_used_tokens_peak", 99999, **h),   # peak > effective
        sample("llm_endpoint_ctx_effective_tokens", 1000, **h),
    ]
    monkeypatch.setattr(prom, "_query", lambda *a, **k: series)
    assert prom.collect()["rows"][0]["ctx_pct"] == 100.0  # clamped, not 9999.9


def test_query_rejects_non_success(monkeypatch):
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"status":"error","error":"boom"}'
    monkeypatch.setattr(prom.urlrequest, "urlopen", lambda *a, **k: FakeResp())
    # collect() swallows it into ok=False
    d = prom.collect()
    assert d["ok"] is False
