"""Embedded OTLP/HTTP-JSON sink — the per-session effort data plane.

Claude Code emits its own telemetry when ``CLAUDE_CODE_ENABLE_TELEMETRY=1`` + ``OTEL_*`` are set in
``settings.json``'s ``env`` block (applied internally to EVERY spawn path — RC bridge / ``--resume``
/ GUI — so one config covers all sessions). The single richest record is the ``api_request`` log
event: keyed by ``session.id``, it carries that request's ``effort`` (low/medium/high/xhigh/max)
plus model/speed/cost/tokens/duration. This is the ONLY source of per-session effort — no local
file exposes it (transcript, /proc/environ, registry, .claude.json all checked).

This sink is a minimal loopback receiver (stdlib only) that rolls up ``session.id -> detail`` and
writes a sidecar for :mod:`cc_monitor.otel` to join. Design decisions:
  * **Dedicated sink** (not a shared external collector): keeps cc-monitor's zero-dependency posture
    and the session-observability concern self-contained.
  * **Per-session detail never enters Prometheus/TSDB** — ``session.id`` is an unbounded churn label
    (the high-cardinality trap ``metrics.py`` deliberately avoids). It lives only in this sidecar.
  * **PII stripped at ingest**: the events also carry ``user.email`` / ``user.id`` /
    ``user.account_*`` / ``organization.id`` — these are dropped in-process and NEVER written. The
    sidecar is 0600 (it holds per-session cost) and the socket binds loopback only.

Transport facts proven by a PoC (Claude Code 2.1.197): the exporter sends ``http/json`` with
**chunked** transfer-encoding (no Content-Length) — so :meth:`_Handler._read_body` must de-chunk —
and may gzip. A payload that isn't valid JSON is logged and dropped, never fatal.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import paths

log = logging.getLogger("cc-monitor")

DEFAULT_HOST = "127.0.0.1"   # loopback ONLY — CC exports locally; never expose the receiver
DEFAULT_PORT = 4318          # OTLP/HTTP default; matches OTEL_EXPORTER_OTLP_ENDPOINT in settings.json
_MAX_SESSIONS = 256          # LRU cap so an always-on sink's sidecar can't grow unbounded
_MAX_SEEN_REQS = 1024        # bound the request-id dedup set (OTLP is at-least-once → retries repeat)

# Identity attributes that must never be persisted (minimised on principle even for a local sink).
_PII = frozenset({"user.email", "user.id", "user.account_id", "user.account_uuid",
                  "organization.id"})


def _av(v):
    """Unwrap an OTLP AnyValue JSON object to a python scalar."""
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (ValueError, TypeError):
            return 0
    if "doubleValue" in v:
        try:
            return float(v["doubleValue"])
        except (ValueError, TypeError):
            return 0.0
    return None


def _attrs(lst) -> dict:
    """OTLP KeyValue list -> flat dict (PII keys dropped here, never held)."""
    out = {}
    for kv in lst or []:
        if isinstance(kv, dict) and kv.get("key") not in _PII and "key" in kv:
            out[kv["key"]] = _av(kv.get("value"))
    return out


class Rollup:
    """Thread-safe ``session.id -> detail`` accumulator, persisted to the sidecar on each change.

    effort/model/speed are **latest-wins** by ``event.sequence`` (a session's effort can change
    mid-run); cost/tokens/count are cumulative across the session's requests, de-duplicated by
    ``request_id`` so an OTLP retry doesn't double-count.
    """

    def __init__(self, path: str | None = None):
        self.path = path or paths.OTEL_FILE
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._seen: dict[str, None] = {}  # request_id -> None, insertion-ordered LRU

    def ingest_logs(self, payload: dict) -> int:
        """Fold every ``api_request`` log record in an OTLP ExportLogsServiceRequest. Returns the
        number of api_request records applied (for tests / diagnostics)."""
        applied = 0
        with self._lock:
            for rl in payload.get("resourceLogs", []) or []:
                res = _attrs(rl.get("resource", {}).get("attributes"))
                for sl in rl.get("scopeLogs", []) or []:
                    for rec in sl.get("logRecords", []) or []:
                        a = {**res, **_attrs(rec.get("attributes"))}
                        name = a.get("event.name") or _av(rec.get("body"))
                        if name != "api_request":
                            continue
                        sid = a.get("session.id")
                        if not sid:
                            continue
                        self._apply(sid, a)
                        applied += 1
            if applied:
                self._write()
        return applied

    def _apply(self, sid: str, a: dict) -> None:
        row = self._sessions.pop(sid, None)  # pop+reinsert = move to MRU end for the LRU cap
        if row is None:
            row = {"effort": None, "model": None, "speed": None, "last_seq": -1,
                   "api_requests": 0, "cost_usd": 0.0,
                   "tokens": {"input": 0, "output": 0, "cacheRead": 0, "cacheCreation": 0}}
        seq = a.get("event.sequence")
        seq = seq if isinstance(seq, int) else row["last_seq"] + 1
        # latest-wins for the display fields: only a request at/after the newest seen seq updates
        # effort/model/speed, so an out-of-order flush can't regress "current effort".
        if seq >= row["last_seq"]:
            row["last_seq"] = seq
            if a.get("effort") is not None:
                row["effort"] = a["effort"]
            if a.get("model"):
                row["model"] = a["model"]
            if a.get("speed"):
                row["speed"] = a["speed"]
        # cumulative fields: dedup by request_id (OTLP at-least-once → the same event can repeat)
        req = a.get("request_id")
        if req is None or req not in self._seen:
            if req is not None:
                self._seen[req] = None
                while len(self._seen) > _MAX_SEEN_REQS:
                    self._seen.pop(next(iter(self._seen)))
            row["api_requests"] += 1
            row["cost_usd"] = round(row["cost_usd"] + float(a.get("cost_usd") or 0), 6)
            t = row["tokens"]
            t["input"] += int(a.get("input_tokens") or 0)
            t["output"] += int(a.get("output_tokens") or 0)
            t["cacheRead"] += int(a.get("cache_read_tokens") or 0)
            t["cacheCreation"] += int(a.get("cache_creation_tokens") or 0)
        self._sessions[sid] = row
        while len(self._sessions) > _MAX_SESSIONS:  # evict the least-recently-updated session
            self._sessions.pop(next(iter(self._sessions)))

    def _write(self) -> None:
        """Atomically write the sidecar at 0600 (holds per-session cost; loopback-derived but kept
        owner-only). sibling .tmp + os.replace so a reader sees old-or-whole, never a torn file."""
        tmp = self.path + ".tmp"
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._sessions, fh, separators=(",", ":"))
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._sessions))  # deep copy for tests


# Cap a single OTLP POST body. Loopback-only, but a runaway/buggy local exporter must not be able
# to force an unbounded read into memory (this tool runs under a co-tenant memory budget).
_MAX_BODY = 8 * 1024 * 1024


def _handler(rollup: Rollup):
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 15

        def _read_body(self) -> bytes:
            """Read the body via Content-Length OR chunked transfer-encoding (the exporter uses
            chunked — no Content-Length — so a naive read returns empty; PoC-proven)."""
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                chunks = []
                total = 0
                while True:
                    size_line = self.rfile.readline().strip()
                    try:
                        size = int(size_line.split(b";")[0], 16)
                    except ValueError:
                        break
                    if size == 0:
                        self.rfile.readline()  # consume trailing CRLF
                        break
                    total += size
                    if total > _MAX_BODY:  # runaway exporter — stop reading, drop the oversized body
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()  # CRLF after each chunk
                return b"".join(chunks)
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            n = min(n, _MAX_BODY)  # cap the declared length before allocating the read
            return self.rfile.read(n) if n > 0 else b""

        def do_POST(self):  # noqa: N802 (stdlib API name)
            try:
                body = self._read_body()
                if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                if self.path.rstrip("/").endswith("/v1/logs"):
                    try:
                        rollup.ingest_logs(json.loads(body))
                    except ValueError:
                        pass  # non-JSON (e.g. protobuf if misconfigured) — drop, never fatal
                # /v1/metrics, /v1/traces: accepted (200) and ignored — log event is the sole source
                self._ok()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                log.exception("cc-monitor otel sink ingest failed")
                try:
                    self._ok()  # still 200 — the exporter must not see this as an endpoint failure
                except OSError:
                    pass

        def _ok(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_a):  # silence per-request logging
            pass

    return _Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class OtelSink:
    """Loopback OTLP receiver on a daemon thread. Best-effort: a bind failure (port taken, telemetry
    disabled) is logged and the dashboard runs without the per-session effort column."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, path: str | None = None):
        self.host, self.port = host, port
        self.rollup = Rollup(path)
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._httpd = _Server((self.host, self.port), _handler(self.rollup))
        except OSError as e:
            log.warning("cc-monitor otel sink not started (%s:%s: %s)", self.host, self.port, e)
            return False
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True,
                                        name="cc-monitor-otel-sink")
        self._thread.start()
        log.info("cc-monitor otel sink on %s:%s -> %s", self.host, self.port, self.rollup.path)
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
