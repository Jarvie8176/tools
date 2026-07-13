"""Filesystem + upstream locations. Overridable via env for testing / non-default installs.

This layer is a Prometheus *consumer* (unlike cc-monitor, which produces metrics). The upstream
Prometheus base URL is a DEPLOY knob — it names an internal, site-specific endpoint, so it lives
in env / install/.env and is NEVER hard-coded here (keeps the public source free of internal hosts).
"""
from __future__ import annotations

import os

# Runtime config file (UI/API-tunable knobs; see config.py). Deploy knobs are NOT here.
CONFIG_FILE = os.path.expanduser(
    os.environ.get("LLM_PM_CONFIG", "~/.config/llm-pipeline-monitor/config.json")
)

# Upstream Prometheus HTTP API base (e.g. an internal reverse-proxy or a tailnet-bound port).
# Neutral localhost default; the real internal URL is supplied via env / install/.env at deploy.
PROM_URL = os.environ.get("LLM_PM_PROM_URL", "http://localhost:9090").rstrip("/")

# Optional query timeout (seconds) for a single Prometheus API call.
PROM_TIMEOUT = float(os.environ.get("LLM_PM_PROM_TIMEOUT", "5"))
