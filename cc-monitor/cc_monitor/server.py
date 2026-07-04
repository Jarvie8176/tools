"""Localhost HTTP server for the dashboard. Binds 127.0.0.1 only (never exposed)."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer

from .collect import collect
from .render import render_html


def _handler(refresh: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (stdlib API name)
            try:
                body = render_html(collect(), refresh=refresh).encode("utf-8")
            except Exception as exc:  # keep the server alive across per-request errors
                body = f"<pre>cc-monitor error: {exc}</pre>".encode()
                self.send_response(500)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # silence request logging
            pass

    return Handler


def serve(port: int, host: str = "127.0.0.1", refresh: int = 3) -> None:
    print(f"cc-monitor serving on http://{host}:{port}  (Ctrl-C to stop)")
    HTTPServer((host, port), _handler(refresh)).serve_forever()
