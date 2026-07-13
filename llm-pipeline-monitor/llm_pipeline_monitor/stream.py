"""Near-real-time push: one server-side poll loop, diffed, fanned out over SSE.

The broker polls the Prometheus adapter (prom.collect) on an interval, serializes to a
change-stable JSON payload, and bumps a version (waking blocked SSE clients) ONLY when the payload
actually changed — so an idle upstream produces no pushes, only heartbeats. Mechanics
(poll→diff→version→fan-out) are the reusable cc-monitor shell; the source is a Prometheus query.

The payload carries no ticking wall-clock field, so it changes only on a REAL metric change; the
client renders absolute values and may animate locally without a server push per interval.
"""
from __future__ import annotations

import json
import logging
import threading

from .prom import collect

log = logging.getLogger("llm-pipeline-monitor")


def serialize(d: dict) -> bytes:
    """Project a prom.collect() result to the stable, compact API payload.

    ``prom_url`` is deliberately NOT on the wire: the UI needs only ok/error for the "upstream
    unreachable" banner, and the no-auth endpoint shouldn't disclose the internal upstream host.
    ``allow_nan=False`` guarantees spec-valid JSON — a stray non-finite would otherwise emit
    ``NaN``/``Infinity`` and break the client's JSON.parse (belt to prom._fval's suspenders)."""
    return json.dumps(
        {"rows": d.get("rows", []), "ok": d.get("ok", False), "error": d.get("error")},
        separators=(",", ":"), allow_nan=False,
    ).encode()


class Broker:
    """Background thread that polls the adapter on an interval, diffs the serialized payload, and
    bumps a version (waking blocked SSE clients) only when it actually changed."""

    def __init__(self, interval: int):
        self.interval = max(1, interval)
        self._cv = threading.Condition()
        self._payload = b'{"rows":[],"ok":false}'
        self._version = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="llm-pm-broker")

    def start(self) -> None:
        self._tick()  # prime once so the first client gets a full snapshot immediately
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _tick(self) -> None:
        try:
            d = collect()  # never raises; ok=False on upstream failure
        except Exception:
            log.exception("llm-pipeline-monitor broker collect failed")  # keep the loop alive
            return
        payload = serialize(d)
        if payload != self._payload:
            with self._cv:
                self._payload = payload
                self._version += 1
                self._cv.notify_all()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._tick()

    def snapshot(self) -> tuple[bytes, int]:
        with self._cv:
            return self._payload, self._version

    def wait(self, last_version: int, timeout: float) -> tuple[bytes, int]:
        """Block until the version moves past ``last_version`` or ``timeout`` elapses (heartbeat)."""
        with self._cv:
            if self._version == last_version:
                self._cv.wait(timeout)
            return self._payload, self._version
