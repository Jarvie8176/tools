"""The SPA shell served at ``/``: SSE-driven (no meta-refresh), XSS-safe by construction, and
routed so ``/legacy`` still serves the server-rendered fallback."""
import re
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from cc_monitor import server, webui


def _page() -> str:
    return webui.spa_page().decode("utf-8")


def test_spa_is_sse_driven_not_meta_refresh():
    p = _page()
    assert "cc-monitor" in p
    assert "EventSource" in p and "/api/stream" in p   # live push, not polling
    assert "http-equiv=refresh" not in p and "http-equiv=\"refresh\"" not in p  # no full-page reload


def test_spa_never_uses_innerhtml():
    # every dynamic field is written via textContent / createElement — asserting innerHTML is absent
    # keeps the page XSS-safe by construction (a hostile session name/prompt can't inject markup).
    assert "innerHTML" not in _page()


def test_spa_has_core_fields_and_controls():
    # Redesign (#1944): zero-horizontal-scroll — the 5 importance-ordered core fields are always
    # present (status -> name -> latest prompt -> context -> idle); the rest drill down into an
    # expand panel. Assert the new invariants: core columns, density presets, settings, endpoints.
    p = _page()
    for label in ("status", "名称", "最新 prompt", "context", "idle"):
        assert label in p, f"missing core field {label!r}"
    for density in ("巡检", "标准", "排查"):               # three density presets (US4)
        assert density in p, f"missing density preset {density!r}"
    assert 'id=filter' in p                            # client-side text filter retained
    assert 'id=settings' in p and 'id=gear' in p       # settings drawer (reveal / theme / thresholds)
    assert '/api/config' in p and '/api/titles' in p   # config read/write + rename writeback (US6)
    assert 'line-clamp' in p                           # CJK visual truncation, not char count (US3)


def test_spa_renders_redaction_marker_as_masked_block():
    # A redacted free-text field arrives as the fixed marker; the page must render it masked
    # (never place the marker text raw, and never inject markup for it).
    p = _page()
    assert "[redacted]" in p and "REDACT_MARK" in p    # client detects the server marker
    assert "innerHTML" not in p


def test_spa_js_is_valid_syntax():
    node = shutil.which("node")
    if not node:  # node ships on CI ubuntu runners + dev host; skip where absent rather than fail
        import pytest
        pytest.skip("node not available for JS syntax check")
    js = re.search(r"<script>\n(.*?)\n</script>", _page(), re.S).group(1)
    r = subprocess.run([node, "--check", "-"], input=js, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _serve():
    # broker-less handler (like test_server): '/' and '/legacy' don't need the SSE broker
    import cc_monitor.server as srv
    orig = srv.collect
    srv.collect = lambda *a, **k: {"ts": 0, "prom": {}, "rows": []}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._handler(server._Cache(3)))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, orig


def _get(url: str):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def test_root_serves_spa_legacy_serves_rendered_html():
    httpd, orig = _serve()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        st, body = _get(base + "/")
        assert st == 200 and b"EventSource" in body and b"http-equiv=refresh" not in body
        st, body = _get(base + "/legacy")
        assert st == 200 and b"http-equiv=refresh" in body and b"<table>" in body  # old fallback
    finally:
        httpd.shutdown()
        server.collect = orig
