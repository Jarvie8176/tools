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
# Per-session OTel rollup sidecar (written by the embedded OTLP sink, read by collect for the
# per-session effort join). Distinct from settings.json's GLOBAL effortLevel — this carries the
# effort of each session's own requests (see otel_sink.py / otel.py). 0600: holds per-session cost.
OTEL_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_OTEL_FILE", os.path.join(CLAUDE_HOME, "cc-monitor-otel.json"))
)
# Declared context window per model id (`{"claude-opus-4-8": 1000000, ...}`), prefilled by
# `cc-monitor models --detect` and then owned by the operator — see windows.py.
WINDOWS_FILE = os.path.expanduser(
    os.environ.get("CC_MONITOR_WINDOWS", os.path.join(CLAUDE_HOME, "cc-monitor-windows.json"))
)
# Claude Code's ~/.claude.json, read ONLY by `models --detect` for `additionalModelOptionsCache` —
# its entries carry fully-qualified model ids bearing the `[<n>m]` suffix for the families the CLI
# offers beyond the built-ins. Never read on the render path; never surfaced wholesale (the file
# also holds oauth account data).
CLAUDE_JSON = os.path.expanduser(
    os.environ.get("CC_MONITOR_CLAUDE_JSON", os.path.join(CLAUDE_HOME, os.pardir, ".claude.json"))
)
