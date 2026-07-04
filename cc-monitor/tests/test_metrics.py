"""Aggregate metrics: exposition formatting, atomic textfile write, broker+/metrics wiring."""
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from cc_monitor import metrics, server, stream


def _row(status, ctx=0, win=200000):
    return {"status": status, "ctx": ctx, "win": win}


def test_exposition_counts_by_status_always_emits_all_labels():
    d = {"rows": [_row("busy"), _row("idle"), _row("idle")], "prom": {}}
    text = metrics.render_exposition(d)
    assert 'cc_monitor_sessions{status="busy"} 1' in text
    assert 'cc_monitor_sessions{status="idle"} 2' in text
    assert 'cc_monitor_sessions{status="orphaned"} 0' in text  # zero series still emitted
    assert "cc_monitor_sessions_total 3" in text


def test_exposition_context_sum_and_pct_max():
    d = {"rows": [_row("busy", ctx=50000), _row("idle", ctx=180000)], "prom": {}}
    text = metrics.render_exposition(d)
    assert "cc_monitor_context_tokens_sum 230000" in text
    assert "cc_monitor_context_pct_max 90.0" in text  # worst-case 180000/200000


def test_pct_max_ignores_unknown_window():
    # a session with an unreadable window (win=0) must not divide-by-zero
    d = {"rows": [{"status": "idle", "ctx": 100, "win": 0}], "prom": {}}
    assert "cc_monitor_context_pct_max 0.0" in metrics.render_exposition(d)


def test_exposition_rc_connected_passthrough():
    assert "cc_monitor_rc_connected 1" in metrics.render_exposition({"rows": [], "prom": {"rc_connected": "1"}})
    assert "cc_monitor_rc_connected 0" in metrics.render_exposition({"rows": [], "prom": {}})


def test_exposition_has_help_type_and_trailing_newline():
    text = metrics.render_exposition({"rows": [], "prom": {}})
    assert "# HELP cc_monitor_up" in text and "# TYPE cc_monitor_up gauge" in text
    assert text.endswith("\n")  # Prometheus exposition ends with a newline


def test_write_textfile_disabled_is_noop():
    metrics.write_textfile("x", "")   # empty path -> writing disabled, no error, no file
    metrics.write_textfile("x", None)


def test_write_textfile_atomic_no_temp_leftover(tmp_path):
    p = tmp_path / "sub" / "cc-monitor.prom"
    metrics.write_textfile("cc_monitor_up 1\n", str(p))
    assert p.read_text() == "cc_monitor_up 1\n"
    assert [f.name for f in (tmp_path / "sub").iterdir()] == ["cc-monitor.prom"]  # temp cleaned up


def test_write_textfile_is_group_readable(tmp_path):
    # mkstemp is 0600; the Alloy textfile collector runs as another uid and must read it — grant
    # GROUP read (0640), not world, so it stays least-privilege
    import os
    p = tmp_path / "cc-monitor.prom"
    metrics.write_textfile("cc_monitor_up 1\n", str(p))
    assert (os.stat(p).st_mode & 0o777) == 0o640


def test_broker_tick_populates_exposition(monkeypatch):
    monkeypatch.setattr(stream, "collect", lambda: {"rows": [_row("busy")], "prom": {}})
    b = stream.Broker(1)
    b._tick()
    assert b'cc_monitor_sessions{status="busy"} 1' in b.exposition()


@pytest.fixture()
def metrics_port(monkeypatch):
    monkeypatch.setattr(stream, "collect", lambda: {"rows": [_row("busy")], "prom": {"rc_connected": "1"}})
    broker = stream.Broker(1)
    broker.start()  # primes one tick -> exposition populated before first request
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._handler(server._Cache(3), broker))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    broker.stop()
    httpd.shutdown()


def test_metrics_endpoint_serves_exposition(metrics_port):
    with urllib.request.urlopen(f"http://127.0.0.1:{metrics_port}/metrics", timeout=3) as r:
        ctype = r.headers["Content-Type"]
        body = r.read().decode()
    assert "text/plain" in ctype
    assert "cc_monitor_up 1" in body and "cc_monitor_rc_connected 1" in body
