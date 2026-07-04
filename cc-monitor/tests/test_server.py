"""Path routing: only '/' serves the dashboard; favicon is 204; everything else 404.

A bare handler used to return the full page for every URL (including /favicon.ico and
/../etc/passwd). Spin up a real server on an ephemeral port and assert the routing.
"""
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from cc_monitor import server


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


def test_root_serves_dashboard(base_url):
    status, body = _get(base_url + "/")
    assert status == 200 and b"cc-monitor" in body


def test_favicon_is_no_content(base_url):
    status, body = _get(base_url + "/favicon.ico")
    assert status == 204 and body == b""


def test_unknown_path_is_404_not_dashboard(base_url):
    status, body = _get(base_url + "/../etc/passwd")
    assert status == 404 and b"cc-monitor" not in body[:5]
