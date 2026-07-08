"""Filesystem locations. Overridable via env for testing / non-default installs."""
from __future__ import annotations

import os

CLAUDE_HOME = os.path.expanduser(os.environ.get("CC_MONITOR_CLAUDE_HOME", "~/.claude"))
PROJECTS_DIR = os.path.join(CLAUDE_HOME, "projects")
SESSIONS_DIR = os.path.join(CLAUDE_HOME, "sessions")
# Claude Code's own settings.json — read ONLY for the display-safe effortLevel (see settings.py).
SETTINGS_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_SETTINGS", os.path.join(CLAUDE_HOME, "settings.json"))
)
TITLES_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_TITLES", os.path.join(CLAUDE_HOME, "cc-monitor-titles.json"))
)
CONFIG_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_CONFIG", os.path.join(CLAUDE_HOME, "cc-monitor-config.json"))
)
CCSESSION_DIR = os.environ.get("CC_MONITOR_CCSESSION_DIR", "/tmp/cc-session")
PROC_DIR = os.environ.get("CC_MONITOR_PROC_DIR", "/proc")
# Textfile metrics target (Alloy textfile-collector dir, e.g. .../textfile/cc-monitor.prom).
# Empty = metrics writing disabled; the deploy opts in since the collector dir is host-specific.
METRICS_FILE = os.path.expanduser(os.environ.get("CC_MONITOR_METRICS_FILE", ""))
