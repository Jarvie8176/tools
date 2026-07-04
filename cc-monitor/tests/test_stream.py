"""Broker diff/version + serialize projection + /api/sessions JSON + /api/stream SSE frame."""
import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from cc_monitor import server, stream


def _row(**kw):
    base = {"session_id": "s", "u8": "u", "pid": 1, "name": "n", "model": "m", "status": "idle",
            "ctx": 0, "peak_ctx": 0, "win": 200000, "win_certain": True, "cum_input": 0,
            "cum_output": 0, "cum_cache": 0, "full": True, "bridge_id": "", "bridge_short": "-",
            "custom_title": "", "override_title": "", "last_prompt": "", "mtime": 123.0,
            "idle_s": 5}
    base.update(kw)
    return base


def test_serialize_uses_absolute_ts_not_ticking_idle():
    d = {"rows": [_row(mtime=999.0, idle_s=42)], "prom": {"workers": "8"}}
    out = json.loads(stream.serialize(d))
    s = out["sessions"][0]
    assert s["last_activity_ts"] == 999.0            # absolute — client ticks idle locally
    assert "idle_s" not in s and "mtime" not in s    # excluded so a clock tick isn't a "change"
    assert out["prom"]["workers"] == "8"


def test_broker_version_bumps_only_on_real_change(monkeypatch):
    seq = [{"rows": [_row(status="idle")], "prom": {}},
           {"rows": [_row(status="idle")], "prom": {}},   # identical -> no bump
           {"rows": [_row(status="busy")], "prom": {}}]   # changed  -> bump
    calls = {"i": 0}

    def fake():
        d = seq[min(calls["i"], len(seq) - 1)]
        calls["i"] += 1
        return d

    monkeypatch.setattr(stream, "collect", fake)
    b = stream.Broker(1)
    b._tick(); _, v1 = b.snapshot()
    b._tick(); _, v2 = b.snapshot()
    b._tick(); _, v3 = b.snapshot()
    assert (v1, v2, v3) == (1, 1, 2)  # identical payload does not bump the version


@pytest.fixture()
def sse_port(monkeypatch):
    monkeypatch.setattr(stream, "collect", lambda: {"rows": [_row()], "prom": {}})
    broker = stream.Broker(1)
    broker.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._handler(server._Cache(3), broker))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    broker.stop()
    httpd.shutdown()


def test_api_sessions_returns_broker_snapshot(sse_port):
    with urllib.request.urlopen(f"http://127.0.0.1:{sse_port}/api/sessions", timeout=3) as r:
        data = json.loads(r.read())
    assert data["sessions"][0]["session_id"] == "s"


def test_api_stream_emits_initial_sse_data_frame(sse_port):
    s = socket.create_connection(("127.0.0.1", sse_port), timeout=3)
    try:
        s.sendall(b"GET /api/stream HTTP/1.1\r\nHost: x\r\n\r\n")
        s.settimeout(3)
        buf = b""
        while b'"sessions"' not in buf and len(buf) < 16384:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    assert b"text/event-stream" in buf       # correct content type
    assert b"data: " in buf and b'"sessions"' in buf  # primed with the current snapshot
