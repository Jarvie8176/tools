"""cc-monitor entry point: text snapshot, HTML file, or localhost server."""
from __future__ import annotations

import argparse
import sys

from . import config, paths, windows
from .collect import collect
from .render import render_html, render_text
from .server import serve


def _pkg_version() -> str:
    """The package version — from __init__.__version__ if present, else installed metadata."""
    try:
        from . import __version__
        return __version__
    except ImportError:  # pragma: no cover — __version__ absent
        from importlib.metadata import version
        return version("cc-monitor")


def _add_redact_flag(sub_parser: argparse.ArgumentParser) -> None:
    """Per-invocation privacy override for a render subcommand. Default None => fall through to
    config file / schema default (redaction is ON by default); the flag is NOT persisted."""
    g = sub_parser.add_mutually_exclusive_group()
    g.add_argument("--redact", dest="redact", action="store_true", default=None,
                   help="mask prompt+title (overrides config; default is on)")
    g.add_argument("--no-redact", dest="redact", action="store_false", default=None,
                   help="show prompt+title in the clear (overrides config)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cc-monitor", description="Live Claude Code session dashboard.")
    p.add_argument("--version", action="version", version=_pkg_version())
    sub = p.add_subparsers(dest="cmd")
    o = sub.add_parser("once", help="print a text snapshot to stdout (default)")
    _add_redact_flag(o)
    h = sub.add_parser("html", help="write a self-refreshing HTML dashboard")
    h.add_argument("path", help="output HTML file path")
    h.add_argument("--refresh", type=int, default=3)
    _add_redact_flag(h)
    s = sub.add_parser("serve", help="run a localhost HTTP dashboard")
    s.add_argument("--port", type=int, default=8899)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--refresh", type=int, default=3)
    # embedded OTLP sink for per-session effort. Loopback only; off => no s-effort column.
    s.add_argument("--no-otel-sink", dest="otel_sink", action="store_false",
                   help="disable the embedded OTLP receiver (per-session effort data plane)")
    s.add_argument("--otel-host", default="127.0.0.1")
    s.add_argument("--otel-port", type=int, default=4318)
    _add_redact_flag(s)

    m = sub.add_parser("models", help="show / prefill the declared context window per model")
    m.add_argument("--detect", action="store_true",
                   help="prefill from evidence (observed peaks, Claude Code's own model options)")
    m.add_argument("--write", action="store_true",
                   help="with --detect, persist the prefill to the windows file")
    return p


def _models(detect: bool, write: bool) -> int:
    """Print the declared window per model; with --detect, prefill undeclared ones from evidence.

    Prefill never overwrites a declaration: an existing entry is echoed back unchanged. A model with
    no evidence is emitted as ``null`` — the operator decides, and until they do the dashboard shows
    '?' rather than a guess.
    """
    current = windows.load()
    mapping = windows.detect() if detect else dict(current)
    if not mapping:
        print("no models seen yet — run a session, then `cc-monitor models --detect`")
        return 0
    peaks = windows.observed_peaks() if detect else {}
    for mid, win in sorted(mapping.items()):
        if mid in current:
            origin = "declared"
        elif win:
            origin = "detected"
        else:
            origin = "UNKNOWN — set this"
        # The peak is the floor we have proven; showing it lets the operator sanity-check a value.
        hint = f"   peak seen {peaks[mid]:,}" if mid in peaks else ""
        print(f"  {mid:<32} {str(win) if win else 'null':>9}   {origin}{hint}")
    if detect and write:
        windows.save(mapping)
        print(f"\nwrote {paths.WINDOWS_FILE}")
    elif detect:
        print("\n(dry run — re-run with --write to persist)")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    cmd = args.cmd or "once"
    # Per-invocation privacy override (highest precedence, not persisted). None => config decides.
    config.set_overrides(redact_default=getattr(args, "redact", None))
    if cmd == "serve":
        serve(args.port, host=args.host, refresh=args.refresh,
              otel_sink=args.otel_sink, otel_host=args.otel_host, otel_port=args.otel_port)
    elif cmd == "html":
        with open(args.path, "w") as fh:
            fh.write(render_html(collect(), refresh=args.refresh))
        print(f"wrote {args.path}")
    elif cmd == "models":
        return _models(detect=args.detect, write=args.write)
    else:
        print(render_text(collect()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
