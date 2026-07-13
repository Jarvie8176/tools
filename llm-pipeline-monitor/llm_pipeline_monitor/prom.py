"""Prometheus-query adapter — the data plane for the LLM-pipeline display layer.

Consumes the isolated ``llm_endpoint_*`` / ``llm_host_*`` series (produced by the endpoint
exporter) from an upstream Prometheus over its HTTP query API, and assembles a per-endpoint row
model for the UI/SSE. Stdlib-only (urllib); never raises to the broker — any upstream failure
degrades to ``ok=False`` + empty rows so the dashboard shows "upstream unreachable", not a crash.

Data direction is the whole point: cc-monitor *produces* metrics (textfile); this layer *queries*
them. One instant query (``{__name__=~"llm_(endpoint|host)_.*"}``) pulls every current series in a
single round-trip; we bucket by the ``host`` label into one row per inference endpoint.
"""
from __future__ import annotations

import json
import logging
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from . import paths

log = logging.getLogger("llm-pipeline-monitor")

# One matcher that captures the whole isolated namespace in a single instant query.
_ALL = '{__name__=~"llm_(endpoint|host)_.*"}'


def _query(base: str, promql: str, timeout: float):
    """Run a Prometheus instant query; return the result[] list. Raises on transport/HTTP/JSON error."""
    url = base + "/api/v1/query?" + urlparse.urlencode({"query": promql})
    with urlrequest.urlopen(url, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    if body.get("status") != "success":
        raise ValueError("prometheus status=%s" % body.get("status"))
    return body.get("data", {}).get("result", [])


def _blank_row(host: str) -> dict:
    return {
        "host": host, "up": 0, "served_id": None, "model_key": None,
        "tok_s_prompt": None, "tok_s_gen": None,
        "active": None, "deferred": None,
        "ctx_used": None, "ctx_peak": None, "ctx_effective": None, "ctx_pct": None,
        "kv_ratio": None,
        "gpu_util": None, "vram_used": None, "vram_total": None, "vram_pct": None,
        "swap_total": 0,
    }


def _fval(sample):
    try:
        return float(sample["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def collect() -> dict:
    """Return ``{"rows": [row,...], "ok": bool, "error": str|None, "prom_url": str}``.

    Never raises — an upstream failure yields ok=False + empty rows (the UI renders a clear
    "upstream unreachable" banner rather than going blank or crashing the broker loop)."""
    base = paths.PROM_URL
    try:
        series = _query(base, _ALL, paths.PROM_TIMEOUT)
    except (URLError, HTTPError, OSError, ValueError, TypeError) as e:
        return {"rows": [], "ok": False, "error": str(e)[:200], "prom_url": base}

    hosts: dict = {}

    def row(h: str) -> dict:
        return hosts.setdefault(h, _blank_row(h))

    for s in series:
        m = s.get("metric") or {}
        name = m.get("__name__")
        host = m.get("host")
        if not name or not host:
            continue
        v = _fval(s)
        if v is None:
            continue
        r = row(host)
        if name == "llm_endpoint_up":
            r["up"] = int(v)
        elif name == "llm_endpoint_resident_model":
            # served_id = observed real gguf (drift-proof), model_key = routing key
            r["served_id"] = m.get("served_id") or r["served_id"]
            r["model_key"] = m.get("model_key") or r["model_key"]
        elif name == "llm_endpoint_tokens_per_second":
            r["tok_s_prompt" if m.get("phase") == "prompt" else "tok_s_gen"] = v
        elif name == "llm_endpoint_active_requests":
            r["active"] = int(v)
        elif name == "llm_endpoint_deferred_requests":
            r["deferred"] = int(v)
        elif name == "llm_endpoint_ctx_used_tokens":
            r["ctx_used"] = int(v)
        elif name == "llm_endpoint_ctx_used_tokens_peak":
            r["ctx_peak"] = int(v)
        elif name == "llm_endpoint_ctx_effective_tokens":
            r["ctx_effective"] = int(v)
        elif name == "llm_endpoint_kv_cache_usage_ratio":
            r["kv_ratio"] = v
        elif name == "llm_endpoint_swap_total":
            r["swap_total"] += v  # sum over (from,to) transitions = total swaps observed
        elif name == "llm_host_gpu_utilization_ratio":
            r["gpu_util"] = v
        elif name == "llm_host_gpu_vram_used_bytes":
            r["vram_used"] = v
        elif name == "llm_host_gpu_vram_total_bytes":
            r["vram_total"] = v

    for r in hosts.values():
        if r["ctx_effective"]:
            used = r["ctx_peak"] if r["ctx_peak"] is not None else r["ctx_used"]
            if used is not None:
                r["ctx_pct"] = round(100.0 * used / r["ctx_effective"], 1)
        if r["vram_total"]:
            r["vram_pct"] = round(100.0 * (r["vram_used"] or 0) / r["vram_total"], 1)
        r["swap_total"] = int(r["swap_total"])

    rows = sorted(hosts.values(), key=lambda r: r["host"])
    return {"rows": rows, "ok": True, "error": None, "prom_url": base}
