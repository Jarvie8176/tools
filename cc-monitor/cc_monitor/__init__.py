"""cc-monitor — independent live dashboard for Claude Code sessions.

Reads authoritative local sources (verified on tp-server, CC 2.1.197):
  - ~/.claude/sessions/<pid>.json   session registry (discovery + busy/idle status)
  - ~/.claude/projects/<slug>/<uuid>.jsonl   transcripts (model / usage / context / title)
  - /proc/<pid>/environ             true context window (200k vs 1M) via [1m] model default
  - /tmp/cc-session/*.{health,prom} cc-session supervisor health (header only)

Design rationale: docs/plans/cc-session-monitor-edd.md (homelab-ops #1763).
"""

__version__ = "0.1.0"
