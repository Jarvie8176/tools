"""Discover live sessions from the registry and assemble dashboard rows.

Driven by ``~/.claude/sessions/<pid>.json`` — the only local source covering BOTH cc-session
``--resume`` workers and RC env-spawned workers (the GUI's set, including the current session).
Enumerating by ``ps --resume`` (the naive approach) misses every env-spawned session.
"""
from __future__ import annotations

import glob
import json
import os
import time

from . import ccsession, config, otel, paths, settings, titles, transcript, window

# Parse cache keyed by path -> ((mtime, size), result). The result carries an internal `_offset`
# byte cursor: on a cache miss we extend the prior parse with only the appended bytes instead of
# re-scanning the whole (tens-of-MB) transcript for the peak-context high-water-mark — the fold is
# the serve loop's cost centre (a 40MB re-parse is ~0.5s vs ~ms incremental). Without any cache the
# server would re-stream every transcript on every refresh and pin the memory cgroup with page
# cache. A session's parse is reused until its transcript's mtime OR size changes (it wrote a line).
_PARSE_CACHE: dict = {}


def _row(result: dict) -> dict:
    """A caller-owned copy of a parse result. Copy because the caller mutates it via `info.update`
    and must not touch the cache; drop the internal `_offset` resume cursor so it never leaks into
    a dashboard row or the /api JSON (the cache keeps it)."""
    row = dict(result)
    row.pop("_offset", None)
    return row


def _parse_cached(path: str) -> dict:
    try:
        st = os.stat(path)
    except OSError:
        return transcript.empty()
    key = (st.st_mtime, st.st_size)
    hit = _PARSE_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return _row(hit[1])  # unchanged since last parse — serve from cache
    # Miss: the transcript grew (or is new). With a prior parse of THIS path, fold only the appended
    # bytes (append-only invariant); parse_incremental falls back to a full parse if it shrank/rotated.
    prev = hit[1] if hit is not None else None
    result = transcript.parse_incremental(path, prev) if prev is not None else transcript.parse(path)
    _PARSE_CACHE[path] = (key, result)
    return _row(result)


def find_transcript(session_id: str, cwd: str) -> str | None:
    """Locate <sid>.jsonl by the cwd-derived slug, falling back to a cross-slug search."""
    slug = cwd.replace("/", "-")
    path = os.path.join(paths.PROJECTS_DIR, slug, f"{session_id}.jsonl")
    if os.path.exists(path):
        return path
    hits = glob.glob(os.path.join(paths.PROJECTS_DIR, "*", f"{session_id}.jsonl"))
    return hits[0] if hits else None


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _proc_liveness(pid, procstart=None) -> str:
    """Classify the worker process: ``gone`` / ``orphaned`` / ``alive``.

    - ``gone``     — no such process, or the PID was recycled (registry ``procStart`` != /proc
      ``starttime``, field 22 / tail index 19). Filtered out of the dashboard.
    - ``orphaned`` — the naive liveness check passes (the PID is still listed in /proc and the
      starttime matches) but the session is NOT actually reachable. Concrete case detected here:
      a defunct process (stat field 3, the char after ``(comm)``, is Z=zombie or X=dead) — it
      exited but wasn't reaped, so it lingers in the process table. This is what would otherwise
      MASQUERADE as a live idle session (its transcript went silent → the mtime heuristic reads
      ``idle``). Broader "alive but RC-unreachable" needs a per-session reachability probe that
      isn't available locally yet (cc-session only exposes an aggregate rc_connected).
    - ``alive``    — a real running/sleeping process (R/S/D/I/T...)."""
    if not pid:
        return "gone"
    try:
        with open(os.path.join(paths.PROC_DIR, str(pid), "stat")) as fh:
            tail = fh.read().rsplit(")", 1)[1].split()  # fields after "(comm)"
    except OSError:
        return "gone"
    if procstart:
        starttime = tail[19] if len(tail) > 19 else None  # field 22 == tail index 19
        if starttime is not None and str(procstart) != starttime:
            return "gone"  # PID recycled — a different process now holds it
    return "orphaned" if (tail and tail[0] in ("Z", "X")) else "alive"


def _status(registry_status, status_ts: float, activity_ts: float, idle_s: float, gap: float) -> str:
    """busy vs active for a registered, reachable session. A session's presence in the registry
    means it has a reachable connection — Claude Code drops the entry when the session ends or its
    connection goes away — so a registered, non-defunct session is **active**, with no time-based
    'idle' tier. 'busy' narrows that to "generating right now": the registry says busy AND that
    status is at least as fresh as the last activity, or the transcript was written within ``gap``
    (``config.busy_idle_gap``). A present-but-defunct process is flagged 'orphaned' upstream."""
    # Honour a registry 'busy' hint ONLY when it is fresh (statusUpdatedAt >= last activity). A
    # timestamp-less (status_ts == 0) or stale busy is NOT trusted — it falls through to the mtime
    # heuristic, so a long-silent session can't stay wrongly 'busy'. Registry 'idle' is never
    # honoured — a registered, reachable session is 'active'.
    if registry_status == "busy" and status_ts >= activity_ts:
        return "busy"
    return "busy" if idle_s < gap else "active"


def collect(now: float | None = None) -> dict:
    """Return ``{"rows": [...], "prom": {...}, "ts": epoch}`` — one row per live session."""
    now = time.time() if now is None else now
    overrides = titles.load()
    gap = config.load()["busy_idle_gap"]
    # settings.json `env`-block model/context keys — global, so read once. These are applied
    # internally by Claude Code and are absent from /proc/environ, so they act as the fallback
    # window signal for workers (e.g. `claude --resume`) whose exec env lacks them. Its mtime gates
    # certainty: a worker that started before the settings were last written may run OLD settings,
    # so we only TRUST the fallback for workers that started at/after this mtime (window.resolve).
    settings_env = settings.model_env()
    settings_mtime = settings.file_mtime()
    # Per-session OTel rollup (effort/cost/tokens keyed by session_id) — None when telemetry is off
    # or the sink never wrote. Read once; join per row. Absent -> per-session effort column stays
    # blank and the GLOBAL settings effortLevel header still shows (optional enrichment, like prom).
    otel_map = otel.read()
    rows = []
    seen_paths = set()
    for reg_path in glob.glob(os.path.join(paths.SESSIONS_DIR, "*.json")):
        try:
            with open(reg_path) as fh:
                reg = json.load(fh)
        except (ValueError, OSError):
            continue
        sid = reg.get("sessionId")
        pid = reg.get("pid")
        live = _proc_liveness(pid, reg.get("procStart"))
        if not sid or live == "gone":
            continue  # stale registry entry / no session id / PID reused (filtered)
        tpath = find_transcript(sid, reg.get("cwd", ""))
        if tpath:
            seen_paths.add(tpath)
        try:
            info = _parse_cached(tpath) if tpath else transcript.empty(_safe_mtime(reg_path))
        except Exception:  # noqa: BLE001 — one malformed transcript must never wedge the whole
            info = transcript.empty()  # table (or silently stop the serve broker); skip this row
        idle_s = max(0.0, now - info["mtime"])  # clamp: a transcript written after `now` was
        #        sampled would otherwise show a negative idle (e.g. "-1s") for an active session
        status_ts = (reg.get("statusUpdatedAt", 0) or 0) / 1000  # registry epoch-ms -> s
        bridge = reg.get("bridgeSessionId") or ""
        # Trust the settings fallback only if this worker demonstrably started under the current
        # settings (its startedAt is at/after the settings mtime). Missing startedAt or a settings
        # edit after start -> untrusted -> the fallback still supplies the window value but flags '?'.
        started_at = reg.get("startedAt")
        settings_trusted = (
            settings_mtime is not None and started_at is not None
            and settings_mtime <= started_at / 1000
        )
        win, win_certain = window.resolve(
            window.read_model_env(pid), settings_env, info.get("model"),
            info.get("peak_ctx", 0), settings_trusted,
        )
        info.update({
            "session_id": sid, "u8": sid[:8], "pid": pid,
            "name": reg.get("name", "-"),
            "bridge_id": bridge,
            "bridge_short": bridge.replace("session_", "s_")[:14] or "-",
            # an orphaned (present-but-not-reachable, e.g. defunct) process would otherwise read
            # as "active" (registered, and its transcript merely went silent) — surface it so a
            # listed-but-dead session is not mistaken for a live, reachable one.
            "status": "orphaned" if live == "orphaned"
            else _status(reg.get("status"), status_ts, info["mtime"], idle_s, gap),
            "idle_s": idle_s,
            "win": win, "win_certain": win_certain,
            "override_title": titles.resolve(overrides, sid, bridge),
        })
        # per-session effort from the OTel sidecar (this session's own requests), distinct from the
        # global settings effortLevel header. None when telemetry is off or this sid hasn't emitted.
        detail = otel_map.get(sid) if otel_map else None
        info["session_effort"] = detail.get("effort") if isinstance(detail, dict) else None
        rows.append(info)
    rows.sort(key=lambda r: (r["status"] != "busy", -r.get("mtime", 0)))
    for dead in [p for p in _PARSE_CACHE if p not in seen_paths]:  # bound cache to live sessions
        del _PARSE_CACHE[dead]
    prom = ccsession.read()  # None when cc-session isn't on this host (optional enrichment)
    return {
        "rows": rows, "prom": prom or {}, "cc_session": prom is not None,
        "effort": settings.effort_level(),  # global CLI effort (settings.json); None if unreadable
        "ts": now,
    }


def title_of(row: dict) -> tuple[str, str]:
    """Return ``(title, source)`` — override > custom-title > '' (cloud-side gap)."""
    if row.get("override_title"):
        return row["override_title"], "override"
    if row.get("custom_title"):
        return row["custom_title"], "custom"
    return "", "cloud-side"
