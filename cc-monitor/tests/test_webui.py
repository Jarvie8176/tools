"""The SPA served at ``/``: a Svelte + Vite build (``webui-src/``) committed as a single self-
contained ``webui_page.html``. SSE-driven (no meta-refresh); ``/legacy`` still serves the no-JS
fallback. XSS-safe by construction: Svelte escapes every ``{text}`` interpolation and the raw-HTML
directive is banned repo-wide (asserted below as a source lint)."""
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from cc_monitor import server, webui

_SRC = Path(__file__).resolve().parent.parent / "webui-src" / "src"


def _page() -> str:
    return webui.spa_page().decode("utf-8")


def test_spa_is_sse_driven_not_meta_refresh():
    p = _page()
    assert "cc-monitor" in p
    assert "EventSource" in p and "/api/stream" in p   # live push, not polling
    assert "http-equiv=refresh" not in p and "http-equiv=\"refresh\"" not in p  # no full-page reload


def test_source_never_uses_raw_html_directive():
    # XSS-safe by construction: Svelte escapes every {text} interpolation; the ONLY way to inject
    # markup would be the raw-HTML directive, which must never appear in the source. (The compiled
    # runtime uses innerHTML internally for STATIC templates — never for session data — so we lint
    # the source for the directive, not the built output for the string.)
    hits = [f for f in _SRC.rglob("*.svelte") if "{@" + "html" in f.read_text(encoding="utf-8")]
    assert not hits, f"raw-HTML directive found in: {hits}"


def test_spa_has_core_fields_and_controls():
    # Redesign (#1944): zero-horizontal-scroll — the 5 importance-ordered core fields are always
    # present (status -> name -> latest prompt -> context -> idle); the rest drill into an expand
    # panel. Assert the built artifact carries the core labels, density presets, and API surface.
    p = _page()
    for label in ("status", "名字", "最新 prompt", "context", "idle"):
        assert label in p, f"missing core field {label!r}"
    for density in ("巡检", "标准", "排查"):               # three density presets (US4)
        assert density in p, f"missing density preset {density!r}"
    assert "来源核对" in p                                 # reconciliation strip (US7/US8)
    assert "/api/config" in p and "/api/titles" in p    # config read/write + rename writeback (US6)
    assert "line-clamp" in p                            # CJK visual truncation, not char count (US3)


def test_spa_renders_redaction_marker_as_masked_block():
    # A redacted free-text field arrives as the fixed marker; the page detects it and renders a
    # masked block (▓) rather than the raw marker text.
    p = _page()
    assert "[redacted]" in p                            # client detects the server marker
    assert "▓" in p                                     # masked-block glyph present in the build


def test_built_artifact_is_self_contained():
    # vite-plugin-singlefile inlines JS + CSS, so the stdlib server serves ONE document with no
    # asset routes. Assert there is no external script/style reference to fetch.
    p = _page()
    assert not re.search(r'<script[^>]*\ssrc=', p), "external <script src> — not self-contained"
    assert not re.search(r'<link[^>]*\shref="[^"]*\.css', p), "external stylesheet — not self-contained"


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
