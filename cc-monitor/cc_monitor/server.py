"""Localhost HTTP server for the dashboard. Binds 127.0.0.1 by default (never exposed unless
a trusted interface is configured). Threaded, with per-connection timeouts and a short render
cache so one slow client or a rapid auto-refresh cannot wedge the whole dashboard."""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, titles, webui
from .collect import collect
from .otel_sink import OtelSink
from .render import render_html
from .stream import Broker

log = logging.getLogger("cc-monitor")
_CONN_TIMEOUT = 15  # seconds; drop slow/half-open connections instead of blocking a worker
_MAX_BODY = 64 * 1024  # cap POST bodies — config is a handful of scalars, never a large payload
_SSE_HEARTBEAT = 10  # seconds; keep the stream/socket alive between changes (< _CONN_TIMEOUT)
_MAX_SSE = 128  # cap concurrent /api/stream connections -> one thread each; bound the resource surface
_BACKLOG = 128  # accept-queue depth; stdlib default 5 gives a ~1s TCP-RTO tail under connection bursts


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


def _handler(cache: _Cache, broker: Broker | None = None):
    # Shared across all handler threads of this server: a hard bound on concurrent SSE streams
    # (each is a long-lived thread). Past the cap, /api/stream is refused with 503 rather than
    # spawning unbounded threads. A value of 0 refuses every stream (used to exercise the path).
    sse_slots = threading.BoundedSemaphore(_MAX_SSE)

    class Handler(BaseHTTPRequestHandler):
        timeout = _CONN_TIMEOUT
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 (stdlib API name)
            # Route on the path so the dashboard isn't served for every URL (a bare handler
            # returned the full page for /favicon.ico, /anything, etc). This is also the seam
            # for future /api + /metrics endpoints.
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            try:
                if path in ("/", "/index.html"):
                    self._ok(webui.spa_page())  # SSE-driven SPA; data via /api/stream, no reload
                elif path in ("/legacy", "/legacy.html"):
                    self._ok(cache.get(time.time()))  # server-rendered <meta refresh> — curl / no-JS
                elif path == "/api/sessions":
                    self._json_bytes(broker.snapshot()[0]) if broker else self._notfound()
                elif path == "/api/stream":
                    self._stream(broker) if broker else self._notfound()  # needs serve() broker
                elif path == "/api/config":
                    self._json(config.load())  # UI/API reads the effective runtime config
                elif path == "/metrics":
                    self._metrics(broker) if broker else self._notfound()  # aggregate exposition
                elif path == "/favicon.ico":
                    self._empty()  # 204; the page also inlines a data-URI icon to avoid the request
                else:
                    self._notfound()
            except (BrokenPipeError, ConnectionResetError):
                pass  # client went away mid-write — normal, not an error
            except Exception:
                log.exception("cc-monitor render failed")  # detail to the server log only
                try:
                    self._fail()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client already gone while sending the error page — nothing to do

        def do_POST(self):  # noqa: N802 (stdlib API name)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            try:
                if path == "/api/config":
                    self._save_config()
                elif path == "/api/titles":
                    self._save_title()
                else:
                    self._notfound()
            except (BrokenPipeError, ConnectionResetError):
                pass  # client went away mid-write — normal, not an error
            except Exception:
                log.exception("cc-monitor POST failed")
                try:
                    self._fail()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client already gone while sending the error — nothing to do

        def _save_config(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_BODY:
                self._json({"error": "bad or missing Content-Length"}, 400)
                return
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                self._json({"error": "invalid JSON"}, 400)
                return
            if not isinstance(data, dict):
                self._json({"error": "expected a JSON object"}, 400)
                return
            # config.save is schema-gated: unknown keys ignored, values coerced+clamped — a POST
            # can only ever set known scalars to in-range values, never write arbitrary content.
            self._json(config.save(data))

        def _save_title(self):
            # US6 title writeback: {key: sessionId|bridgeSessionId, title: str}. Empty title clears
            # the override. Only the local override map is touched (never a transcript); a bad body
            # is a 400, so a malformed client request can't write junk.
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_BODY:
                self._json({"error": "bad or missing Content-Length"}, 400)
                return
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                self._json({"error": "invalid JSON"}, 400)
                return
            key = data.get("key") if isinstance(data, dict) else None
            if not isinstance(key, str) or not key.strip():
                self._json({"error": "missing or empty 'key'"}, 400)
                return
            title = data.get("title")
            if title is not None and not isinstance(title, str):
                self._json({"error": "'title' must be a string"}, 400)
                return
            titles.save(key.strip(), title or "")  # empty/None -> clear override
            self._json({"ok": True})

        def _ok(self, body: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._json_bytes(json.dumps(obj).encode("utf-8"), status)

        def _json_bytes(self, body: bytes, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self, broker: Broker):
            # Server-Sent Events: one long-lived HTTP response, `data:` frames on each change and a
            # comment heartbeat between changes. No Content-Length (open-ended); the browser's
            # EventSource reconnects on its own if the socket drops.
            if not sse_slots.acquire(blocking=False):  # cap concurrent streams (bounded threads)
                self._json({"error": "too many concurrent streams"}, 503)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")  # ask proxies not to buffer the stream
                self.end_headers()
                payload, ver = broker.snapshot()
                self.wfile.write(b"data: " + payload + b"\n\n")  # prime with the current snapshot
                self.wfile.flush()
                while True:
                    payload, newver = broker.wait(ver, _SSE_HEARTBEAT)
                    if newver != ver:
                        ver = newver
                        self.wfile.write(b"data: " + payload + b"\n\n")
                    else:
                        self.wfile.write(b": ping\n\n")  # heartbeat — no change this interval
                    self.wfile.flush()
            finally:
                sse_slots.release()  # runs on disconnect (BrokenPipe/timeout) — frees the slot

        def _metrics(self, broker: Broker):
            # Serve the broker's cached exposition (refreshed each collect tick) — the same text
            # written to the textfile collector. No extra collect() per scrape.
            body = broker.exposition()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _empty(self):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _notfound(self):
            msg = b"cc-monitor: not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

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


class _Server(ThreadingHTTPServer):
    daemon_threads = True     # a hung request thread must not block process exit
    request_queue_size = _BACKLOG  # stdlib default 5 -> ~1s TCP-RTO tail under connection bursts


def serve(port: int, host: str = "127.0.0.1", refresh: int = 3,
          otel_sink: bool = True, otel_host: str = "127.0.0.1", otel_port: int = 4318) -> None:
    cache = _Cache(refresh)
    broker = Broker(refresh)  # single collect loop feeding /api/sessions + /api/stream (SSE)
    sink = None
    if otel_sink:  # embedded per-session effort data plane; best-effort — a bind failure
        sink = OtelSink(host=otel_host, port=otel_port)  # (port taken/telemetry off) just no column
        sink.start()
    try:  # warm the parse + render caches before binding, so the first request is instant
        cache.get(time.time())
        broker.start()
    except Exception:
        log.exception("cc-monitor initial warm failed")
    httpd = _Server((host, port), _handler(cache, broker))
    print(f"cc-monitor serving on http://{host}:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    finally:
        if sink is not None:
            sink.stop()
