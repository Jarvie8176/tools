"""Read cc-session supervisor health — an OPTIONAL enrichment, not a dependency.

cc-monitor is a standalone Claude Code session dashboard (discovery is Claude Code's own
``~/.claude/sessions`` registry, not cc-session). When it happens to run on a host that ALSO runs
the cc-session supervisor, it surfaces that supervisor's health in the header. When cc-session is
absent, ``read`` returns ``None`` so the caller shows a plain standalone view — NOT a misleading
"RC DOWN". These files are the supervisor's own view; ``workers``/``capacity`` come from tmux pane
scraping and are unreliable (the very fragility this dashboard routes around) — shown for context,
never used as session truth.
"""
from __future__ import annotations

import os

from . import paths


def read(ccsession_dir: str | None = None) -> dict | None:
    """Parse claude.prom into a flat dict; ``None`` if absent (no cc-session on this host).

    ``None`` (absent) is distinct from ``{}`` (present but empty/unparseable): the caller uses it to
    decide whether cc-session integration applies at all, vs. present-but-unhealthy.
    """
    path = os.path.join(ccsession_dir or paths.CCSESSION_DIR, "claude.prom")
    try:
        fh = open(path)
    except OSError:
        return None  # no claude.prom -> cc-session not present here; caller renders standalone
    with fh:
        prom = {}
        for line in fh:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                prom[key] = val
    return prom
