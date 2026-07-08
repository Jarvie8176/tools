"""Prometheus metrics — aggregate session gauges, exposed two ways.

Follows the node-exporter textfile-collector convention: the PRIMARY path is an atomically-written
``*.prom`` under the node-exporter textfile dir (e.g. ``/var/lib/node-exporter/textfile_collector``),
read off disk by the existing node-exporter — NOT an HTTP scrape target (cc-monitor binds a trusted
interface only). The same exposition text is also served at ``GET /metrics`` for local validation.

Metrics are AGGREGATE with BOUNDED labels, never per-session. A ``session_id`` label would be an
UNBOUNDED, churning label — every new session mints a permanently-retained series (the cardinality
trap) and leaks session identity into the TSDB. Per-session detail lives in the dashboard/API;
Prometheus holds only low-cardinality, alertable signals: counts by status, the worst-case context
utilisation (a session near its window), and RC connectivity.

Two exposition contracts this file honours:
- ``# HELP``/``# TYPE`` appear ONCE per metric family, never per series — node-exporter rejects the
  WHOLE file otherwise.
- every expected series is emitted even at 0 (all statuses, rc), so an absence-based alert can tell
  a real zero from a dead writer; plus a ``cc_monitor_timestamp_seconds`` staleness watchdog.

Writing is DISABLED unless ``CC_MONITOR_METRICS_FILE`` (paths.METRICS_FILE) is set — the collector
dir is host-specific, so the deploy opts in; a dev/laptop run writes nothing by default.
"""
from __future__ import annotations

import os

# Fixed status label set — always emitted (even at 0) so the series exists for alerting: a missing
# series and a genuine zero are indistinguishable to an absence-based alert, so we never omit one.
_STATUSES = ("busy", "idle", "orphaned")


def _fmt(v) -> str:
    """Render a metric value: ints bare, floats trimmed. Prometheus wants a plain number."""
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(int(v))


def render_exposition(d: dict) -> str:
    """Format a collect() result as Prometheus text exposition (aggregate gauges)."""
    rows = d["rows"]
    counts = {s: 0 for s in _STATUSES}
    for r in rows:
        st = r.get("status")
        if st in counts:
            counts[st] += 1
    ctx_sum = sum(int(r.get("ctx", 0) or 0) for r in rows)
    # worst-case utilisation across sessions with a known (non-zero) window
    pct_max = 0.0
    for r in rows:
        win = r.get("win") or 0
        if win:
            pct_max = max(pct_max, 100.0 * (r.get("ctx", 0) or 0) / win)
    out = []

    def metric(name, help_, typ, samples):
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {typ}")
        out.extend(samples)

    metric("cc_monitor_up", "cc-monitor exporter is running.", "gauge",
           ["cc_monitor_up 1"])
    metric("cc_monitor_timestamp_seconds", "Unix time this exposition was generated (staleness "
           "watchdog).", "gauge", [f"cc_monitor_timestamp_seconds {_fmt(d.get('ts', 0))}"])
    metric("cc_monitor_sessions", "Live registry sessions by status.", "gauge",
           [f'cc_monitor_sessions{{status="{s}"}} {counts[s]}' for s in _STATUSES])
    metric("cc_monitor_sessions_total", "Total live registry sessions.", "gauge",
           [f"cc_monitor_sessions_total {len(rows)}"])
    metric("cc_monitor_context_tokens_sum", "Sum of input-side context tokens across sessions.",
           "gauge", [f"cc_monitor_context_tokens_sum {_fmt(ctx_sum)}"])
    metric("cc_monitor_context_pct_max", "Highest per-session context-window utilisation (0-100).",
           "gauge", [f"cc_monitor_context_pct_max {_fmt(pct_max)}"])
    if d.get("cc_session"):  # only when the cc-session supervisor is on this host — absence of the
        rc = 1 if d["prom"].get("rc_connected") == "1" else 0  # series means "N/A", not "RC down"
        metric("cc_monitor_rc_connected", "cc-session remote-control connectivity (1=connected).",
               "gauge", [f"cc_monitor_rc_connected {rc}"])
    return "\n".join(out) + "\n"  # exposition text ends with a trailing newline


def write_textfile(text: str, path: str | None) -> None:
    """Atomically write exposition ``text`` to ``path`` (no-op if ``path`` is falsy).

    Atomic via a sibling ``.tmp`` + ``os.replace`` in the SAME dir: node-exporter scrapes ``*.prom``
    only, so the transient ``.tmp`` is never read, and the rename makes the reader see either the
    old file or the whole new one — never a torn half.

    Uses a plain ``open`` (NOT ``tempfile.mkstemp``, which forces 0600) so the file lands at the
    process umask — 0644 under the systemd unit (UMask 022). That matches the fleet convention: the
    node-exporter textfile collector runs as ``nobody`` and reads the world-readable ``*.prom`` the
    other ccrc-written generators already produce (e.g. ``cc_session_mem.prom``). A hardcoded chmod
    would either be too tight (0600 → nobody can't read) or trip CodeQL (world/group read); letting
    umask decide is both correct here and how every other textfile generator does it.
    """
    if not path:
        return  # writing disabled — deploy sets CC_MONITOR_METRICS_FILE to the collector dir
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
