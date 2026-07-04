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

from . import ccsession, paths, titles, transcript, window

BUSY_IDLE_GAP = 12  # seconds; env-spawned workers lack a status field -> mtime heuristic


def find_transcript(session_id: str, cwd: str) -> str | None:
    """Locate <sid>.jsonl by the cwd-derived slug, falling back to a cross-slug search."""
    slug = cwd.replace("/", "-")
    path = os.path.join(paths.PROJECTS_DIR, slug, f"{session_id}.jsonl")
    if os.path.exists(path):
        return path
    hits = glob.glob(os.path.join(paths.PROJECTS_DIR, "*", f"{session_id}.jsonl"))
    return hits[0] if hits else None


def _proc_alive(pid) -> bool:
    return bool(pid) and os.path.exists(os.path.join(paths.PROC_DIR, str(pid)))


def _status(registry_status, idle_s: float) -> str:
    if registry_status == "busy":
        return "busy"
    if registry_status == "idle":
        return "idle"
    return "busy" if idle_s < BUSY_IDLE_GAP else "idle"


def collect(now: float | None = None) -> dict:
    """Return ``{"rows": [...], "prom": {...}, "ts": epoch}`` — one row per live session."""
    now = time.time() if now is None else now
    overrides = titles.load()
    rows = []
    for reg_path in glob.glob(os.path.join(paths.SESSIONS_DIR, "*.json")):
        try:
            with open(reg_path) as fh:
                reg = json.load(fh)
        except (ValueError, OSError):
            continue
        sid = reg.get("sessionId")
        pid = reg.get("pid")
        if not sid or not _proc_alive(pid):
            continue  # stale registry entry / no session id
        tpath = find_transcript(sid, reg.get("cwd", ""))
        info = transcript.parse(tpath) if tpath else transcript.empty(os.path.getmtime(reg_path))
        idle_s = now - info["mtime"]
        bridge = reg.get("bridgeSessionId") or ""
        win, win_certain = window.resolve_window(
            window.read_model_env(pid), info.get("model"), info.get("peak_ctx", 0)
        )
        info.update({
            "session_id": sid, "u8": sid[:8], "pid": pid,
            "name": reg.get("name", "-"),
            "bridge_id": bridge,
            "bridge_short": bridge.replace("session_", "s_")[:14] or "-",
            "status": _status(reg.get("status"), idle_s),
            "idle_s": idle_s,
            "win": win, "win_certain": win_certain,
            "override_title": titles.resolve(overrides, sid, bridge),
        })
        rows.append(info)
    rows.sort(key=lambda r: (r["status"] != "busy", -r.get("mtime", 0)))
    return {"rows": rows, "prom": ccsession.read(), "ts": now}


def title_of(row: dict) -> tuple[str, str]:
    """Return ``(title, source)`` — override > custom-title > '' (cloud-side gap)."""
    if row.get("override_title"):
        return row["override_title"], "override"
    if row.get("custom_title"):
        return row["custom_title"], "custom"
    return "", "cloud-side"
