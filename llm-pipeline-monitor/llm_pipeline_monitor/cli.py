"""llm-pipeline-monitor entry point: text snapshot or localhost server."""
from __future__ import annotations

import argparse
import sys

from .prom import collect
from .server import serve


def _pkg_version() -> str:
    try:
        from . import __version__
        return __version__
    except ImportError:  # pragma: no cover
        from importlib.metadata import version
        return version("llm-pipeline-monitor")


def _fmt(v, suffix=""):
    return "?" if v is None else f"{v}{suffix}"


def render_text(d: dict) -> str:
    """One line per endpoint — a stdout snapshot for curl/debug (no server)."""
    if not d.get("ok"):
        return f"upstream unreachable ({d.get('prom_url')}): {d.get('error')}"
    if not d.get("rows"):
        return f"no llm_endpoint_* series in upstream ({d.get('prom_url')})"
    out = []
    for r in d["rows"]:
        served = r.get("served_id") or r.get("model_key") or "?"
        out.append(
            f"{r['host']:<10} up={r['up']} model={served} "
            f"tok/s(p/g)={_fmt(r['tok_s_prompt'])}/{_fmt(r['tok_s_gen'])} "
            f"ctx={_fmt(r['ctx_used'])}/{_fmt(r['ctx_effective'])}({_fmt(r['ctx_pct'],'%')}) "
            f"gpu={_fmt(r['gpu_util'])} vram={_fmt(r['vram_pct'],'%')} swaps={r['swap_total']}"
        )
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llm-pipeline-monitor",
                                description="Live local LLM-pipeline dashboard (Prometheus-fed).")
    p.add_argument("--version", action="version", version=_pkg_version())
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("once", help="print a text snapshot to stdout (default)")
    s = sub.add_parser("serve", help="run a localhost HTTP dashboard")
    s.add_argument("--port", type=int, default=8896)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--refresh", type=int, default=5)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    cmd = args.cmd or "once"
    if cmd == "serve":
        serve(port=args.port, host=args.host, refresh=args.refresh)
        return 0
    print(render_text(collect()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
