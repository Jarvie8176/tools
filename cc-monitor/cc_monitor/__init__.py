"""cc-monitor — independent live dashboard for Claude Code sessions.

Reads authoritative local sources (verified against Claude Code 2.1.x):
  - ~/.claude/sessions/<pid>.json   session registry (discovery + busy/idle status)
  - ~/.claude/projects/<slug>/<uuid>.jsonl   transcripts (model / usage / context / title)
  - /proc/<pid>/environ             true context window (200k vs 1M) via [1m] model default
  - /tmp/cc-session/*.{health,prom} cc-session supervisor health (header only)

See the README for the design rationale.
"""

__version__ = "0.1.0"
