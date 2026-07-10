"""Near-real-time push: one server-side collect loop, diffed, fanned out over SSE.

Evaluation (measured on a live host, 16 live sessions):
  * steady-state warm collect() = ~2ms (parse cache: unchanged transcripts aren't re-read);
    the cost is the per-CHANGE re-parse of a large transcript (~0.5s for 40MB), which no
    transport avoids — so the transport is a second-order concern.
  * transcript writes are seconds apart, not a ms flood → sub-second latency buys no perceptible
    UX on a human-watched panel; a 1-2s cadence already "feels live".
Hence SSE over a single interval poll — not WebSocket (bidirectional we don't need; stdlib has no
WS, so it'd mean hand-rolled framing or a new dep) and not inotify yet (needs a dep + debounce;
the parse cache already makes idle polling ~free and naturally coalesces write bursts).

The diff excludes wall-clock-derived fields: each row carries ``last_activity_ts`` (absolute
transcript mtime), NOT a ticking ``idle_s`` — so the payload changes only on a REAL change (a
write, a status flip, a new/gone session), and the client derives+ticks idle locally. That makes
the push genuinely event-driven instead of firing every interval just because a clock advanced.
"""
from __future__ import annotations

import json
import logging
import threading

from . import config, metrics, paths, privacy
from .collect import collect

log = logging.getLogger("cc-monitor")

# Free-text fields masked when redact_default is on — same set the HTML/text renderers redact.
_REDACT_FIELDS = ("custom_title", "override_title", "initial_prompt", "last_prompt")

# Row fields exposed over the API. `mtime` is remapped to `last_activity_ts` (absolute) so the
# client can tick idle locally without a server push; `idle_s`/`ts` are deliberately excluded
# from the payload so a mere clock advance is not a "change".
_API_FIELDS = (
    "session_id", "u8", "pid", "name", "model", "status",
    "ctx", "peak_ctx", "win", "win_certain", "win_conflict",
    "cum_input", "cum_output", "cum_cache", "full",
    "bridge_id", "bridge_short", "custom_title", "override_title",
    "initial_prompt", "last_prompt", "session_effort",
    "origin", "managed", "bridged",
)


def serialize(d: dict) -> bytes:
    """Project a collect() result to the stable API payload (compact, change-stable JSON).

    When ``redact_default`` is on, the free-text fields are masked HERE — the real prompt/title
    never enter the payload, so an API/SSE client cannot recover them (safe-by-default: there is
    nothing to un-blur without an authenticated server round-trip, tracked for M-C)."""
    on = config.load()["redact_default"]
    sessions = []
    for r in d["rows"]:
        s = {k: r.get(k) for k in _API_FIELDS}
        for f in _REDACT_FIELDS:
            s[f] = privacy.redact(s.get(f), on)
        s["last_activity_ts"] = r.get("mtime")
        sessions.append(s)
    return json.dumps(
        {"sessions": sessions, "prom": d["prom"], "cc_session": d.get("cc_session", False),
         "effort": d.get("effort"), "recon": d.get("recon", {})},
        separators=(",", ":"),
    ).encode()


class Broker:
    """Background thread that polls collect() on an interval, diffs the serialized payload, and
    bumps a version (waking blocked SSE clients) only when it actually changed."""

    def __init__(self, interval: int):
        self.interval = max(1, interval)
        self._cv = threading.Condition()
        self._payload = b'{"sessions":[],"prom":{}}'
        self._version = 0
        self._exposition = b""  # latest Prometheus exposition (for GET /metrics); atomic ref swap
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="cc-monitor-broker")

    def start(self) -> None:
        self._tick()  # prime once so the first client gets a full snapshot immediately
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _tick(self) -> None:
        try:
            d = collect()  # one collect per tick feeds BOTH the SSE payload and the metrics
        except Exception:
            log.exception("cc-monitor broker collect failed")  # keep the loop alive
            return
        # Notify SSE clients FIRST: serialize + version bump before touching the textfile, so a
        # slow/full metrics disk can never delay the push (the write is best-effort, the push isn't).
        payload = serialize(d)
        if payload != self._payload:
            with self._cv:
                self._payload = payload
                self._version += 1
                self._cv.notify_all()
        try:  # metrics are best-effort — a write error/slowness must not stall the stream loop
            expo = metrics.render_exposition(d)
            self._exposition = expo.encode()
            metrics.write_textfile(expo, paths.METRICS_FILE)
        except Exception:
            log.exception("cc-monitor metrics write failed")

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._tick()

    def snapshot(self) -> tuple[bytes, int]:
        with self._cv:
            return self._payload, self._version

    def exposition(self) -> bytes:
        """Latest Prometheus exposition bytes (empty until the first successful tick)."""
        return self._exposition

    def wait(self, last_version: int, timeout: float) -> tuple[bytes, int]:
        """Block until the version moves past ``last_version`` or ``timeout`` elapses (heartbeat)."""
        with self._cv:
            if self._version == last_version:
                self._cv.wait(timeout)
            return self._payload, self._version
