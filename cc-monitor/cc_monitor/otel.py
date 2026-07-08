"""Read the per-session OTel rollup sidecar — an OPTIONAL enrichment, not a dependency.

The sidecar (``~/.claude/cc-monitor-otel.json``, keyed by ``session.id``) is produced by the
embedded OTLP sink (see :mod:`cc_monitor.otel_sink`) from Claude Code's own telemetry. It carries
the ONE per-session fact no local file exposes — the effort each session actually ran its requests
at — plus cost/token roll-ups. When telemetry isn't enabled (no ``CLAUDE_CODE_ENABLE_TELEMETRY``
env in settings.json, or no session has emitted yet), :func:`read` returns ``None`` and the caller
falls back to the GLOBAL ``settings.json effortLevel`` header (same absent≠error contract as
:mod:`cc_monitor.ccsession`).

``session.id`` in OTel == the transcript filename == cc-monitor's ``session_id`` — so the join is a
direct dict lookup; no correlation heuristic. Stale entries (ended sessions) are harmless: no live
row matches them, so they simply don't render (the sink LRU-bounds the file's growth).
"""
from __future__ import annotations

import json

from . import paths


def read(path: str | None = None) -> dict | None:
    """Parse the sidecar into ``{session_id: detail}``; ``None`` if absent/unreadable.

    ``None`` (telemetry off / sink never wrote) is distinct from ``{}`` (present but empty): the
    caller uses it only to decide whether the per-session effort column applies at all.
    """
    try:
        with open(path or paths.OTEL_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
