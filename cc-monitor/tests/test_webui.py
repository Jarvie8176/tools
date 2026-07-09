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


def test_spa_has_expected_columns_and_controls():
    p = _page()
    for col in ("status", "uuid8", "name", "title", "initial-prompt", "last-prompt",
                "model", "s-effort", "context", "cum in/out", "idle", "bridge"):
        assert col in p, f"missing column {col!r}"
    assert 'id=filter' in p and 'id=sort' in p        # client-side filter + sort controls
    assert '/api/config' in p                         # picks up runtime ctx colour thresholds


def test_spa_has_settings_panel():
    p = _page()
    assert 'id=cfgbtn' in p and 'id=settings' in p     # ⚙ toggle + panel container
    assert '/api/config/schema' in p                   # renders inputs from the exposed schema
    assert 'buildSettings' in p and 'saveSettings' in p
    # the save path must POST — never a GET that mutates
    assert 'method:"POST"' in p or "method: 'POST'" in p
    # audit fixes: a cleared number field is a no-op (not a silent reset to min), and a save
    # repaints existing rows with the new colour thresholds instead of waiting for the next tick.
    assert 'Number.isNaN' in p
    assert 'reconcile(); buildSettings()' in p


def test_spa_truncates_free_text_columns():
    # a long initial/last prompt must be clipped client-side — otherwise a nowrap cell grows to the
    # full text width and pushes the right-hand columns (model … bridge) off-screen. Mirrors
    # render.trunc, honouring the prompt/title_trunc_html config caps.
    p = _page()
    assert "function clip(" in p
    assert "clip(r.initial_prompt" in p and "clip(r.last_prompt" in p
    assert "prompt_trunc_html" in p and "title_trunc_html" in p
    # CSS hard bound too: char-clipping alone still lets 70 CJK chars stretch the column, and the
    # free-text cells carry the clamp class so the max-width actually applies.
    assert "td.clamp{max-width" in p and 'dim clamp"' in p
    assert "td.wrap{max-width" in p


def test_spa_ctx_bar_fill_is_block():
    # .bar is a <span>; without display:block an inline element ignores width/height, so the
    # coloured fill rendered at zero size and every context bar looked like an empty grey pill.
    assert ".bar{display:block" in _page()


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
