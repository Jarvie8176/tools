"""cc-monitor entry point: text snapshot, HTML file, or localhost server."""
from __future__ import annotations

import argparse
import sys

from .collect import collect
from .render import render_html, render_text
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cc-monitor", description="Live Claude Code session dashboard.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("once", help="print a text snapshot to stdout (default)")
    h = sub.add_parser("html", help="write a self-refreshing HTML dashboard")
    h.add_argument("path", help="output HTML file path")
    h.add_argument("--refresh", type=int, default=3)
    s = sub.add_parser("serve", help="run a localhost HTTP dashboard")
    s.add_argument("--port", type=int, default=8899)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--refresh", type=int, default=3)
    # embedded OTLP sink for per-session effort. Loopback only; off => no s-effort column.
    s.add_argument("--no-otel-sink", dest="otel_sink", action="store_false",
                   help="disable the embedded OTLP receiver (per-session effort data plane)")
    s.add_argument("--otel-host", default="127.0.0.1")
    s.add_argument("--otel-port", type=int, default=4318)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    cmd = args.cmd or "once"
    if cmd == "serve":
        serve(args.port, host=args.host, refresh=args.refresh,
              otel_sink=args.otel_sink, otel_host=args.otel_host, otel_port=args.otel_port)
    elif cmd == "html":
        with open(args.path, "w") as fh:
            fh.write(render_html(collect(), refresh=args.refresh))
        print(f"wrote {args.path}")
    else:
        print(render_text(collect()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
