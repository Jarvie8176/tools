# llm-pipeline-monitor

An independent, live dashboard for a **local LLM inference pipeline**. It reads the isolated
`llm_endpoint_*` / `llm_host_*` metric namespace from an upstream **Prometheus** and renders, per
inference endpoint:

- **resident model** — the *observed served gguf* (drift-proof: the real artifact, not a config
  alias), plus its routing key;
- **throughput** — prompt / generation tok/s (flags generation below a configurable floor: the
  classic "GPU silently dropped offload" regression);
- **host GPU / VRAM** — system-level utilisation and VRAM (Metal has no per-process VRAM
  attribution, so VRAM is a host-level ceiling, not per-session);
- **per-session context** — used vs effective `n_ctx`, with a peak that captures short-lived slots;
- **model-swap events** — swap count (an on-demand single-resident server swaps models in/out).

Data arrives over Server-Sent Events; the UI is a single self-contained page (no build step at
deploy time). The dashboard is **read-only** and has **no auth** — bind localhost, or a trusted
tailnet interface behind an edge reverse proxy.

## Relationship to cc-monitor

This tool **reuses the `cc-monitor` operational shell** — the stdlib HTTP server, the SSE broker,
the schema-gated config plane, the single-file Svelte/Vite SPA pipeline, and the systemd `--user`
deploy pattern — but with a **different data plane and direction**:

|                | cc-monitor                          | llm-pipeline-monitor                 |
|----------------|-------------------------------------|--------------------------------------|
| domain         | Claude Code sessions (per-session)  | LLM inference endpoints (infra)      |
| data source    | local transcripts / `/proc`         | upstream **Prometheus** (HTTP query) |
| data direction | **produces** metrics (textfile)     | **consumes** metrics (PromQL)        |

They share a design system and shell, not a process — two decoupled apps. As further pipeline legs
(gateway spend, digest) land as Prometheus series, this layer extends to show them.

## Architecture

```
Prometheus (llm_endpoint_* / llm_host_*)          upstream, HTTP query API
        │  prom.collect()  — one instant query, bucketed by `host` into per-endpoint rows
        ▼
stdlib HTTP server  ──►  /               single-file Svelte SPA (webui_page.html)
   (server.py)      ──►  /api/stream     SSE: change-diffed row payload (stream.Broker)
                    ──►  /api/snapshot    JSON snapshot
                    ──►  /api/config      GET/POST runtime thresholds (config.py)
```

Stdlib only (`dependencies = []`): the backend queries Prometheus with `urllib`. Any upstream
failure degrades to an "upstream unreachable" banner — never a crash or a blank page.

## Install

```
cd install
cp .env.example .env      # set LLM_PM_PROM_URL to your Prometheus endpoint; adjust PORT/HOST
./deploy.sh               # idempotent: pipx install + systemd --user unit
```

`LLM_PM_PROM_URL` is the only site-specific value and lives in `install/.env` (gitignored). The
exposure pattern for remote viewing is an edge reverse proxy over a trusted tailnet interface —
never bind `0.0.0.0` (no auth).

## Config

Runtime-tunable thresholds (persisted to `~/.config/llm-pipeline-monitor/config.json`, editable in
the UI or via `POST /api/config`, schema-gated + clamped):

| knob            | default | meaning                                        |
|-----------------|---------|------------------------------------------------|
| `ctx_warn_pct`  | 50      | per-session context bar → amber above this     |
| `ctx_crit_pct`  | 80      | per-session context bar → red above this       |
| `vram_warn_pct` | 85      | host VRAM bar → amber above this               |
| `tps_floor`     | 15      | generation tok/s below this = flagged (G3)     |

## Develop

```
# Python
pip install -e ".[dev]"
pytest

# Web UI (rebuild the committed single-file artifact after editing webui-src/)
cd webui-src && npm ci && npm run check && npm run build   # emits ../llm_pipeline_monitor/webui_page.html

# CLI snapshot (no server) — set the upstream, then:
LLM_PM_PROM_URL=http://prometheus.internal.example:9090 llm-pipeline-monitor once
```

License: Apache-2.0.
