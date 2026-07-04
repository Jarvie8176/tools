"""Filesystem locations. Overridable via env for testing / non-default installs."""
from __future__ import annotations

import os

CLAUDE_HOME = os.path.expanduser(os.environ.get("CC_MONITOR_CLAUDE_HOME", "~/.claude"))
PROJECTS_DIR = os.path.join(CLAUDE_HOME, "projects")
SESSIONS_DIR = os.path.join(CLAUDE_HOME, "sessions")
TITLES_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_TITLES", os.path.join(CLAUDE_HOME, "cc-monitor-titles.json"))
)
CONFIG_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_CONFIG", os.path.join(CLAUDE_HOME, "cc-monitor-config.json"))
)
CCSESSION_DIR = os.environ.get("CC_MONITOR_CCSESSION_DIR", "/tmp/cc-session")
PROC_DIR = os.environ.get("CC_MONITOR_PROC_DIR", "/proc")
