"""Hermetic fixtures — all data synthetic (no real fleet sessions/keys/addrs)."""
from __future__ import annotations

import json
import os

import pytest

from cc_monitor import paths


class FakeClaude:
    """Builds a fake ~/.claude tree + /proc so collect() runs against temp dirs."""

    def __init__(self, root: str):
        self.root = root
        self.sessions = os.path.join(root, "sessions")
        self.projects = os.path.join(root, "projects")
        self.proc = os.path.join(root, "proc")
        self.ccsession = os.path.join(root, "ccsession")
        for d in (self.sessions, self.projects, self.proc, self.ccsession):
            os.makedirs(d, exist_ok=True)
        self.titles_file = os.path.join(root, "titles.json")
        self.settings_file = os.path.join(root, "settings.json")

    def proc_alive(self, pid, env: dict | None = None, starttime="12345", state="S"):
        d = os.path.join(self.proc, str(pid))
        os.makedirs(d, exist_ok=True)
        blob = b"".join(f"{k}={v}".encode() + b"\0" for k, v in (env or {}).items())
        with open(os.path.join(d, "environ"), "wb") as fh:
            fh.write(blob)
        # /proc/<pid>/stat: field 3 (state) is index 0 after "(comm)"; field 22 (starttime) index 19
        tail = [state] + ["0"] * 18 + [str(starttime)] + ["0"] * 5
        with open(os.path.join(d, "stat"), "w") as fh:
            fh.write(f"{pid} (claude) " + " ".join(tail))

    def transcript(self, session_id, cwd, events):
        slug = cwd.replace("/", "-")
        d = os.path.join(self.projects, slug)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{session_id}.jsonl")
        with open(path, "w") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")
        return path

    def registry(self, pid, session_id, cwd, name="cc-xx", status=None, bridge=None,
                 procstart=None, status_updated_at=None, started_at=None):
        rec = {"pid": pid, "sessionId": session_id, "cwd": cwd, "name": name}
        if status:
            rec["status"] = status
        if bridge:
            rec["bridgeSessionId"] = bridge
        if procstart is not None:
            rec["procStart"] = procstart
        if status_updated_at is not None:
            rec["statusUpdatedAt"] = status_updated_at
        if started_at is not None:
            rec["startedAt"] = started_at
        with open(os.path.join(self.sessions, f"{pid}.json"), "w") as fh:
            json.dump(rec, fh)

    def titles(self, mapping: dict):
        with open(self.titles_file, "w") as fh:
            json.dump(mapping, fh)

    def settings(self, mapping: dict):
        with open(self.settings_file, "w") as fh:
            json.dump(mapping, fh)


@pytest.fixture
def claude(tmp_path, monkeypatch):
    fc = FakeClaude(str(tmp_path))
    monkeypatch.setattr(paths, "SESSIONS_DIR", fc.sessions)
    monkeypatch.setattr(paths, "PROJECTS_DIR", fc.projects)
    monkeypatch.setattr(paths, "PROC_DIR", fc.proc)
    monkeypatch.setattr(paths, "CCSESSION_DIR", fc.ccsession)
    monkeypatch.setattr(paths, "TITLES_FILE", fc.titles_file)
    # Point at a fake (absent) settings.json so effort reads are hermetic — a test opts in by
    # calling fc.settings({...}); default is unreadable -> effort None (no real ~/.claude read).
    monkeypatch.setattr(paths, "SETTINGS_FILE", fc.settings_file)
    return fc


def assistant(model, inp, cache_read=0, cache_creation=0, out=0):
    return {"type": "assistant", "message": {"model": model, "usage": {
        "input_tokens": inp, "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation, "output_tokens": out}}}


def user(text, kind=None):
    ev = {"type": "user", "message": {"content": text}}
    if kind is not None:
        ev["origin"] = {"kind": kind}
    return ev


def custom_title(t):
    return {"type": "custom-title", "customTitle": t}
