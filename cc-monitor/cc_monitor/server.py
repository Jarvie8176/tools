"""Localhost HTTP server for the dashboard. Binds 127.0.0.1 by default (never exposed unless
a trusted interface is configured). Threaded, with per-connection timeouts and a short render
cache so one slow client or a rapid auto-refresh cannot wedge the whole dashboard."""
from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .collect import collect
from .render import render_html

log = logging.getLogger("cc-monitor")
_CONN_TIMEOUT = 15  # seconds; drop slow/half-open connections instead of blocking a worker


class _Cache:
    """Serve a rendered page for up to `ttl` seconds so concurrent clients and the page's own
    auto-refresh don't each trigger a full collect()."""

    def __init__(self, refresh: int):
        self.ttl = max(1, min(refresh, 3))
        self.lock = threading.Lock()
        self.at = 0.0
        self.body = b""

    def get(self, now: float) -> bytes:
        # Single-flight: render under the lock so concurrent clients (and the page's own refresh)
        # wait for ONE render instead of each launching a full collect() — no thundering herd.
        with self.lock:
            if self.body and now - self.at < self.ttl:
                return self.body
            self.body = render_html(collect(), refresh=self.ttl).encode("utf-8")
            self.at = time.time()
            return self.body


def _handler(cache: _Cache):
    class Handler(BaseHTTPRequestHandler):
        timeout = _CONN_TIMEOUT
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 (stdlib API name)
            try:
                body = cache.get(time.time())
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # client went away mid-write — normal, not an error
            except Exception:
                log.exception("cc-monitor render failed")  # detail to the server log only
                try:
                    self._fail()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def _fail(self):
            msg = b"cc-monitor: internal error (see server log)"  # never echo the exception
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

        def log_message(self, *_args):  # silence per-request logging
            pass

    return Handler


def serve(port: int, host: str = "127.0.0.1", refresh: int = 3) -> None:
    cache = _Cache(refresh)
    try:  # warm the parse + render caches before binding, so the first request is instant
        cache.get(time.time())
    except Exception:
        log.exception("cc-monitor initial warm failed")
    httpd = ThreadingHTTPServer((host, port), _handler(cache))
    httpd.daemon_threads = True
    print(f"cc-monitor serving on http://{host}:{port}  (Ctrl-C to stop)")
    httpd.serve_forever()
