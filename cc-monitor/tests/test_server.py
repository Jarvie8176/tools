"""Path routing: only '/' serves the dashboard; favicon is 204; everything else 404.

A bare handler used to return the full page for every URL (including /favicon.ico and
/../etc/passwd). Spin up a real server on an ephemeral port and assert the routing.
"""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from cc_monitor import config, paths, server


@pytest.fixture()
def base_url(monkeypatch):
    # collect() reads the fleet's real ~/.claude; stub it so the test is hermetic and fast.
    monkeypatch.setattr(server, "collect", lambda *a, **k: {"ts": 0, "prom": {}, "rows": []})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._handler(server._Cache(3)))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(url, raw: bytes):
    req = urllib.request.Request(url, data=raw, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_root_serves_dashboard(base_url):
    status, body = _get(base_url + "/")
    assert status == 200 and b"cc-monitor" in body


def test_favicon_is_no_content(base_url):
    status, body = _get(base_url + "/favicon.ico")
    assert status == 204 and body == b""


def test_unknown_path_is_404_not_dashboard(base_url):
    status, body = _get(base_url + "/../etc/passwd")
    assert status == 404 and b"cc-monitor" not in body[:5]


def test_api_config_get_then_post_persists(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    config._cache[0] = None  # invalidate the (key, value) tuple cache
    status, body = _get(base_url + "/api/config")
    assert status == 200
    assert json.loads(body)["ctx_warn_pct"] == config.DEFAULTS["ctx_warn_pct"]

    status, body = _post(base_url + "/api/config", json.dumps({"ctx_warn_pct": 42, "nope": 1}).encode())
    assert status == 200
    got = json.loads(body)
    assert got["ctx_warn_pct"] == 42 and "nope" not in got  # schema-gated

    status, body = _get(base_url + "/api/config")
    assert json.loads(body)["ctx_warn_pct"] == 42  # GET reflects the persisted change


def test_api_config_post_rejects_bad_json(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    status, _ = _post(base_url + "/api/config", b"{not json")
    assert status == 400


def test_api_config_post_rejects_non_object(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    status, _ = _post(base_url + "/api/config", b"[1,2,3]")
    assert status == 400


def test_api_titles_post_writes_override(base_url, tmp_path, monkeypatch):
    tf = tmp_path / "titles.json"
    monkeypatch.setattr(paths, "TITLES_FILE", str(tf))
    status, body = _post(base_url + "/api/titles",
                         json.dumps({"key": "uuid-1", "title": "Renamed"}).encode())
    assert status == 200 and json.loads(body) == {"ok": True}
    from cc_monitor import titles
    assert titles.load(str(tf)) == {"uuid-1": "Renamed"}


def test_api_titles_post_empty_clears(base_url, tmp_path, monkeypatch):
    tf = tmp_path / "titles.json"
    monkeypatch.setattr(paths, "TITLES_FILE", str(tf))
    _post(base_url + "/api/titles", json.dumps({"key": "uuid-1", "title": "X"}).encode())
    _post(base_url + "/api/titles", json.dumps({"key": "uuid-1", "title": ""}).encode())
    from cc_monitor import titles
    assert "uuid-1" not in titles.load(str(tf))


def test_api_titles_post_rejects_missing_key(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TITLES_FILE", str(tmp_path / "titles.json"))
    status, _ = _post(base_url + "/api/titles", json.dumps({"title": "no key"}).encode())
    assert status == 400
    status, _ = _post(base_url + "/api/titles", json.dumps({"key": "  ", "title": "blank"}).encode())
    assert status == 400


def test_api_titles_post_rejects_bad_json(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "TITLES_FILE", str(tmp_path / "titles.json"))
    status, _ = _post(base_url + "/api/titles", b"{not json")
    assert status == 400


def test_spa_and_api_are_not_cached(base_url):
    # US2: the SPA shell + JSON API must revalidate each load so a redeploy / config change is seen
    # immediately, never served from a stale browser/proxy cache (#108).
    for path in ("/", "/api/config"):
        with urllib.request.urlopen(base_url + path) as r:
            assert r.headers.get("Cache-Control") == "no-cache", path


def test_server_widens_accept_backlog():
    # stdlib default request_queue_size=5 gives a ~1s TCP-RTO tail under bursts; we widen it
    assert server._Server.request_queue_size == 128
    assert server._Server.daemon_threads is True


def test_stream_refused_past_connection_cap(monkeypatch):
    # with the SSE cap set to 0, /api/stream must be refused with 503, never spawn a stream thread
    monkeypatch.setattr(server, "_MAX_SSE", 0)
    from cc_monitor import stream
    broker = stream.Broker(1)
    monkeypatch.setattr(stream, "collect", lambda: {"rows": [], "prom": {}})
    broker.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._handler(server._Cache(3), broker))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, body = _get(f"http://127.0.0.1:{httpd.server_address[1]}/api/stream")
        assert status == 503 and b"too many concurrent streams" in body
    finally:
        broker.stop()
        httpd.shutdown()


def test_api_models_post_persists(base_url, tmp_path, monkeypatch):
    mf = str(tmp_path / "models.json")
    monkeypatch.setattr(paths, "MODELS_FILE", mf)
    status, body = _post(base_url + "/api/models",
                         json.dumps({"model": "claude-opus-4-8", "alias": "Opus", "window": 500000}).encode())
    assert status == 200 and json.loads(body) == {"ok": True}
    from cc_monitor import models
    assert models.load(mf) == {"claude-opus-4-8": {"alias": "Opus", "window": 500000}}


def test_api_models_post_clears_fields(base_url, tmp_path, monkeypatch):
    mf = str(tmp_path / "models.json")
    monkeypatch.setattr(paths, "MODELS_FILE", mf)
    _post(base_url + "/api/models", json.dumps({"model": "m", "alias": "A", "window": 300000}).encode())
    _post(base_url + "/api/models", json.dumps({"model": "m", "alias": "", "window": None}).encode())
    from cc_monitor import models
    assert models.load(mf) == {}                      # both fields cleared -> entry dropped


def test_api_models_rejects_missing_model(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "MODELS_FILE", str(tmp_path / "models.json"))
    status, _ = _post(base_url + "/api/models", json.dumps({"alias": "no model"}).encode())
    assert status == 400
    status, _ = _post(base_url + "/api/models", json.dumps({"model": "  "}).encode())
    assert status == 400


def test_api_models_rejects_float_and_bool_window(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "MODELS_FILE", str(tmp_path / "models.json"))
    # a float would be silently truncated by int() downstream — reject at the boundary instead
    status, _ = _post(base_url + "/api/models", json.dumps({"model": "m", "window": 200000.9}).encode())
    assert status == 400
    status, _ = _post(base_url + "/api/models", json.dumps({"model": "m", "window": True}).encode())
    assert status == 400


def test_api_models_rejects_bad_json(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "MODELS_FILE", str(tmp_path / "models.json"))
    status, _ = _post(base_url + "/api/models", b"{not json")
    assert status == 400
