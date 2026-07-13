"""HTTP server smoke — routes serve over a real socket. prom.collect is stubbed (no upstream)."""
from __future__ import annotations

import json
import threading
import urllib.request
from urllib.error import HTTPError

import pytest

from llm_pipeline_monitor import server, stream
from llm_pipeline_monitor.server import _Server, _handler

GGUF = "/models/synthetic-7b.gguf"
_SNAP = {"rows": [{"host": "node-a", "up": 1, "served_id": GGUF, "model_key": "syn",
                   "tok_s_gen": 40, "swap_total": 0}], "ok": True, "error": None,
         "prom_url": "http://localhost:9090"}


@pytest.fixture
def live_server(monkeypatch, cfg_file):
    monkeypatch.setattr(stream, "collect", lambda: dict(_SNAP))
    broker = stream.Broker(1)
    broker.start()
    httpd = _Server(("127.0.0.1", 0), _handler(broker))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()
    broker.stop()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def test_snapshot(live_server):
    status, body = _get(live_server + "/api/snapshot")
    assert status == 200
    d = json.loads(body)
    assert d["ok"] is True
    assert d["rows"][0]["served_id"] == GGUF  # real gguf survives the payload


def test_index_serves_spa(live_server):
    status, body = _get(live_server + "/")
    assert status == 200
    assert b"<html" in body.lower()


def test_config_get(live_server):
    status, body = _get(live_server + "/api/config")
    assert status == 200
    assert json.loads(body)["ctx_warn_pct"] == 50


def test_config_post_clamped(live_server):
    req = urllib.request.Request(
        live_server + "/api/config", method="POST",
        data=json.dumps({"ctx_crit_pct": 999}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        assert json.loads(r.read())["ctx_crit_pct"] == 100


def test_unknown_route_404(live_server):
    with pytest.raises(HTTPError) as e:
        _get(live_server + "/nope")
    assert e.value.code == 404


def test_favicon_204(live_server):
    status, _ = _get(live_server + "/favicon.ico")
    assert status == 204
