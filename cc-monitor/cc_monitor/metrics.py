"""Prometheus metrics — aggregate session gauges, exposed two ways.

Aligned with the fleet's textfile-collector convention (#1416/#1239): the PRIMARY path is an
atomically-written ``*.prom`` file that Alloy's textfile collector reads off disk — NOT an HTTP
scrape target. cc-monitor binds a trusted interface only; standing up a scrape port would widen
the surface for no gain when the collector already sweeps a textfile dir. The same exposition
text is also served at ``GET /metrics`` for local validation (``curl`` the running instance).

Metrics are AGGREGATE, never per-session: a ``session="<uuid>"`` label would be high-cardinality
and would leak session identity into the TSDB — the same exposure ``redact_default`` guards on the
UI. The useful fleet signals are low-cardinality: counts by status, and the worst-case context
utilisation (a session approaching its window is the thing worth alerting on).

Writing is DISABLED unless ``CC_MONITOR_METRICS_FILE`` (paths.METRICS_FILE) is set — the textfile
collector dir is host-specific, so the deploy opts in; a dev/laptop run writes nothing by default.
"""
from __future__ import annotations

import os
import tempfile

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
    rc = 1 if d.get("prom", {}).get("rc_connected") == "1" else 0

    out = []

    def metric(name, help_, typ, samples):
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} {typ}")
        out.extend(samples)

    metric("cc_monitor_up", "cc-monitor exporter is running.", "gauge",
           ["cc_monitor_up 1"])
    metric("cc_monitor_sessions", "Live registry sessions by status.", "gauge",
           [f'cc_monitor_sessions{{status="{s}"}} {counts[s]}' for s in _STATUSES])
    metric("cc_monitor_sessions_total", "Total live registry sessions.", "gauge",
           [f"cc_monitor_sessions_total {len(rows)}"])
    metric("cc_monitor_context_tokens_sum", "Sum of input-side context tokens across sessions.",
           "gauge", [f"cc_monitor_context_tokens_sum {_fmt(ctx_sum)}"])
    metric("cc_monitor_context_pct_max", "Highest per-session context-window utilisation (0-100).",
           "gauge", [f"cc_monitor_context_pct_max {_fmt(pct_max)}"])
    metric("cc_monitor_rc_connected", "cc-session remote-control connectivity (1=connected).",
           "gauge", [f"cc_monitor_rc_connected {rc}"])
    return "\n".join(out) + "\n"  # exposition text ends with a trailing newline


def write_textfile(text: str, path: str | None) -> None:
    """Atomically write exposition ``text`` to ``path`` (no-op if ``path`` is falsy).

    Atomic (temp + os.replace in the SAME dir) because the textfile collector may scrape mid-write;
    a rename makes the reader see either the old file or the whole new one, never a torn half.
    """
    if not path:
        return  # writing disabled — deploy sets CC_MONITOR_METRICS_FILE to the collector dir
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cc-monitor-metrics.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)  # mkstemp is 0600; the textfile collector often runs as another uid,
        #                       and the metrics are non-sensitive aggregates — make them readable
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
