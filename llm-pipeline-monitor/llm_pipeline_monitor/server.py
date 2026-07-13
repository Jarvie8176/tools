"""Localhost HTTP server for the dashboard. Binds 127.0.0.1 by default (never exposed unless a
trusted interface is configured — the documented exposure is a tailnet IP behind an edge proxy,
NOT 0.0.0.0, since there is no auth). Threaded, per-connection timeouts, bounded SSE fan-out.

Reused verbatim from the cc-monitor shell minus its cc-session-specific routes (title writeback,
legacy HTML render, textfile /metrics): this layer serves an SSE-driven SPA over a Prometheus-fed
data plane."""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, webui
from .stream import Broker

log = logging.getLogger("llm-pipeline-monitor")
_CONN_TIMEOUT = 15  # seconds; drop slow/half-open connections instead of blocking a worker
_MAX_BODY = 64 * 1024  # cap POST bodies — config is a handful of scalars, never a large payload
_SSE_HEARTBEAT = 10  # seconds; keep the stream/socket alive between changes (< _CONN_TIMEOUT)
_MAX_SSE = 128  # cap concurrent /api/stream connections -> one thread each; bound the resource surface
_BACKLOG = 128  # accept-queue depth; stdlib default 5 gives a ~1s TCP-RTO tail under connection bursts


def _handler(broker: Broker):
    import threading
    # Shared across handler threads: a hard bound on concurrent SSE streams (each a long-lived
    # thread). Past the cap, /api/stream is refused with 503 rather than spawning unbounded threads.
    sse_slots = threading.BoundedSemaphore(_MAX_SSE)

    class Handler(BaseHTTPRequestHandler):
        timeout = _CONN_TIMEOUT
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 (stdlib API name)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            try:
                if path in ("/", "/index.html"):
                    self._ok(webui.spa_page())  # SSE-driven SPA; data via /api/stream, no reload
                elif path == "/api/snapshot":
                    self._json_bytes(broker.snapshot()[0])
                elif path == "/api/stream":
                    self._stream(broker)
                elif path == "/api/config":
                    self._json(config.load())  # UI/API reads the effective runtime config
                elif path == "/favicon.ico":
                    self._empty()  # 204; the page also inlines a data-URI icon to avoid the request
                else:
                    self._notfound()
            except (BrokenPipeError, ConnectionResetError):
                pass  # client went away mid-write — normal, not an error
            except Exception:
                log.exception("llm-pipeline-monitor render failed")  # detail to the server log only
                try:
                    self._fail()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_POST(self):  # noqa: N802 (stdlib API name)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            try:
                if path == "/api/config":
                    self._save_config()
                else:
                    self._notfound()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                log.exception("llm-pipeline-monitor POST failed")
                try:
                    self._fail()
                except (BrokenPipeError, ConnectionResetError):
                    pass

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

        def _ok(self, body: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")  # revalidate SPA shell so a redeploy lands
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._json_bytes(json.dumps(obj).encode("utf-8"), status)

        def _json_bytes(self, body: bytes, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self, broker: Broker):
            # Server-Sent Events: one long-lived HTTP response, `data:` frames on each change and a
            # comment heartbeat between changes. No Content-Length; EventSource reconnects on drop.
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

        def _empty(self):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _notfound(self):
            msg = b"llm-pipeline-monitor: not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

        def _fail(self):
            msg = b"llm-pipeline-monitor: internal error (see server log)"  # never echo the exception
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


def serve(port: int, host: str = "127.0.0.1", refresh: int = 3) -> None:
    broker = Broker(refresh)  # single poll loop feeding /api/snapshot + /api/stream (SSE)
    try:  # warm the first snapshot before binding, so the first request is instant
        broker.start()
    except Exception:
        log.exception("llm-pipeline-monitor initial warm failed")
    httpd = _Server((host, port), _handler(broker))
    print(f"llm-pipeline-monitor serving on http://{host}:{port}  (Ctrl-C to stop)")
    httpd.serve_forever()
