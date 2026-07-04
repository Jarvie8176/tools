"""Read cc-session supervisor health for the dashboard header (display only).

These files are the supervisor's own view; ``workers``/``capacity`` come from tmux pane
scraping and are unreliable (the very fragility this dashboard routes around) — shown for
context, never used as session truth.
"""
from __future__ import annotations

import os

from . import paths


def read(ccsession_dir: str | None = None) -> dict:
    """Parse claude.prom into a flat dict; {} if absent."""
    prom = {}
    path = os.path.join(ccsession_dir or paths.CCSESSION_DIR, "claude.prom")
    try:
        with open(path) as fh:
            for line in fh:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    prom[key] = val
    except OSError:
        pass  # claude.prom absent (no cc-session on this host) — header just omits its fields
    return prom
