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

from . import ccsession, config, paths, titles, transcript, window

# Parse cache keyed by path -> ((mtime, size), result). Transcripts are read fully to compute the
# peak-context high-water-mark, and the live set can be hundreds of MB; without this, the server
# would re-stream every transcript on every refresh and pin the memory cgroup with page cache.
# A session's parse is reused until its transcript's mtime OR size changes (i.e. it wrote a line).
_PARSE_CACHE: dict = {}


def _parse_cached(path: str) -> dict:
    try:
        st = os.stat(path)
    except OSError:
        return transcript.empty()
    key = (st.st_mtime, st.st_size)
    hit = _PARSE_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return dict(hit[1])  # copy — the caller mutates (info.update) and must not touch the cache
    result = transcript.parse(path)
    _PARSE_CACHE[path] = (key, result)
    return dict(result)


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


def _proc_alive(pid, procstart=None) -> bool:
    """Alive AND the same process — guards against PID reuse. The registry ``procStart`` equals
    /proc/<pid>/stat field 22 (starttime, clock ticks); a mismatch means the PID was recycled."""
    if not pid:
        return False
    try:
        with open(os.path.join(paths.PROC_DIR, str(pid), "stat")) as fh:
            tail = fh.read().rsplit(")", 1)[1].split()  # fields after "(comm)"
    except OSError:
        return False
    if procstart:
        starttime = tail[19] if len(tail) > 19 else None  # field 22 == tail index 19
        if starttime is not None and str(procstart) != starttime:
            return False
    return True


def _status(registry_status, status_ts: float, activity_ts: float, idle_s: float, gap: float) -> str:
    """busy/idle. Registry status is trusted only while it is at least as fresh as the last
    observed activity — a stale 'idle' (statusUpdatedAt older than the transcript write) does NOT
    mask a session that has since done work; it falls through to the activity heuristic.

    ``gap`` is the config'd busy->idle silence threshold (``config.busy_idle_gap``)."""
    # Trust the registry status unless we KNOW it is stale (have a statusUpdatedAt older than the
    # last activity). status_ts == 0 means "no timestamp" -> don't distrust, use the status as-is.
    if registry_status in ("busy", "idle") and (status_ts == 0 or status_ts >= activity_ts):
        return registry_status
    return "busy" if idle_s < gap else "idle"  # no status, or status stale vs activity


def collect(now: float | None = None) -> dict:
    """Return ``{"rows": [...], "prom": {...}, "ts": epoch}`` — one row per live session."""
    now = time.time() if now is None else now
    overrides = titles.load()
    gap = config.load()["busy_idle_gap"]
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
        if not sid or not _proc_alive(pid, reg.get("procStart")):
            continue  # stale registry entry / no session id / PID reused
        tpath = find_transcript(sid, reg.get("cwd", ""))
        if tpath:
            seen_paths.add(tpath)
        try:
            info = _parse_cached(tpath) if tpath else transcript.empty(_safe_mtime(reg_path))
        except OSError:
            info = transcript.empty()
        idle_s = max(0.0, now - info["mtime"])  # clamp: a transcript written after `now` was
        #        sampled would otherwise show a negative idle (e.g. "-1s") for an active session
        status_ts = (reg.get("statusUpdatedAt", 0) or 0) / 1000  # registry epoch-ms -> s
        bridge = reg.get("bridgeSessionId") or ""
        win, win_certain = window.resolve_window(
            window.read_model_env(pid), info.get("model"), info.get("peak_ctx", 0)
        )
        info.update({
            "session_id": sid, "u8": sid[:8], "pid": pid,
            "name": reg.get("name", "-"),
            "bridge_id": bridge,
            "bridge_short": bridge.replace("session_", "s_")[:14] or "-",
            "status": _status(reg.get("status"), status_ts, info["mtime"], idle_s, gap),
            "idle_s": idle_s,
            "win": win, "win_certain": win_certain,
            "override_title": titles.resolve(overrides, sid, bridge),
        })
        rows.append(info)
    rows.sort(key=lambda r: (r["status"] != "busy", -r.get("mtime", 0)))
    for dead in [p for p in _PARSE_CACHE if p not in seen_paths]:  # bound cache to live sessions
        del _PARSE_CACHE[dead]
    return {"rows": rows, "prom": ccsession.read(), "ts": now}


def title_of(row: dict) -> tuple[str, str]:
    """Return ``(title, source)`` — override > custom-title > '' (cloud-side gap)."""
    if row.get("override_title"):
        return row["override_title"], "override"
    if row.get("custom_title"):
        return row["custom_title"], "custom"
    return "", "cloud-side"
