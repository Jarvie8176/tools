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
import math
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
    # collect() rejects any non-http(s) PROM_URL before calling here, so urlopen can't be steered
    # to a file:// read; the base is an operator-set config value, not request input.
    with urlrequest.urlopen(url, timeout=timeout) as resp:  # nosec B310
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
    # Prometheus emits the strings "NaN"/"+Inf"/"-Inf" (zero-denominator ratios, counter resets).
    # float() accepts them, but non-finite values crash int() and serialize to invalid JSON
    # (NaN/Infinity), which kills the SSE client's JSON.parse. Reject them → None → renders "?".
    try:
        f = float(sample["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return f if math.isfinite(f) else None


def _ts(sample):
    try:
        return float(sample["value"][0])
    except (KeyError, IndexError, ValueError, TypeError):
        return -1.0


def collect() -> dict:
    """Return ``{"rows": [row,...], "ok": bool, "error": str|None, "prom_url": str}``.

    Never raises — an upstream failure yields ok=False + empty rows (the UI renders a clear
    "upstream unreachable" banner rather than going blank or crashing the broker loop)."""
    base = paths.PROM_URL
    if not base.startswith(("http://", "https://")):
        # never let urllib follow file://, gopher://, etc. — the upstream is operator-set, but a
        # typo'd scheme should fail loud, not open a local-file read.
        return {"rows": [], "ok": False, "error": "PROM_URL must be http(s)", "prom_url": base}
    try:
        series = _query(base, _ALL, paths.PROM_TIMEOUT)
    except (URLError, HTTPError, OSError, ValueError, TypeError) as e:
        return {"rows": [], "ok": False, "error": str(e)[:200], "prom_url": base}

    hosts: dict = {}
    rm_ts: dict = {}  # host -> timestamp of the chosen resident_model sample (pick the latest)

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
            # served_id = observed real gguf (drift-proof), model_key = routing key. After a swap
            # the OLD series is still returned within Prometheus lookback-delta (~5m) with value 1,
            # so order-dependent last-wins could pin a stale gguf. Adopt only value>0 AND the
            # LATEST-timestamp sample per host → the current resident wins deterministically.
            ts = _ts(s)
            if v > 0 and ts >= rm_ts.get(host, -1.0):
                rm_ts[host] = ts
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

    def _pct(num, den):
        # clamp to [0,100] — a negative/zero effective or peak>effective would otherwise feed a
        # nonsense colour-threshold and overflow the UI bar.
        if not den or den <= 0 or num is None:
            return None
        return round(max(0.0, min(100.0, 100.0 * num / den)), 1)

    for r in hosts.values():
        used = r["ctx_peak"] if r["ctx_peak"] is not None else r["ctx_used"]
        r["ctx_pct"] = _pct(used, r["ctx_effective"])
        # pass vram_used straight (NOT `or 0`): a MISSING used with a present total must stay None
        # (→ "?"), not masquerade as a healthy 0%. A real 0 still yields 0% (0 is not None).
        r["vram_pct"] = _pct(r["vram_used"], r["vram_total"])
        r["swap_total"] = int(r["swap_total"])

    rows = sorted(hosts.values(), key=lambda r: r["host"])
    return {"rows": rows, "ok": True, "error": None, "prom_url": base}
