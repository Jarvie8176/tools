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

import glob
import os

from . import paths


def managed_ledger(ccsession_dir: str | None = None) -> set[str]:
    """The supervisor's worker ledger — the set of session ``uuid8``s that have a ``claude-*.url``
    file in the cc-session dir (cc-session writes one per worker it manages). Empty when cc-session
    isn't on this host. The uuid8 is the **second-to-last** dash segment of
    ``claude-<host>-<uuid8>-<hash>.url`` — taken from the end so a hostname containing dashes can't
    shift it. ``claude.url`` (the RC's own, no dashes) and the supervisor's ``cc-*.url`` don't match
    the ``claude-*`` worker shape and are excluded.

    Distinct from ``read()``'s scraped ``workers`` count: this ledger is a real per-worker artefact,
    whereas ``workers`` is an unreliable tmux-pane scrape — the drift between them is exactly what
    the reconciliation surfaces."""
    d = ccsession_dir or paths.CCSESSION_DIR
    ledger = set()
    for p in glob.glob(os.path.join(d, "claude-*.url")):
        parts = os.path.basename(p)[:-4].split("-")  # drop ".url", split on '-'
        if len(parts) >= 4:  # claude, <host…>, <uuid8>, <hash>
            ledger.add(parts[-2])
    return ledger


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
