# cc-monitor

Independent, **standalone** live dashboard for **Claude Code sessions** on any host running Claude
Code. Shows, per session: **model · token usage · context size (with true 200k/1M window) ·
running status**. Discovery reads Claude Code's own `~/.claude/sessions` registry — it does **not**
depend on the [cc-session](../cc-session/) supervisor. When cc-session *does* run on the same host,
its supervisor health is surfaced in the header as an optional enrichment; when it doesn't, the
dashboard shows a plain standalone view (no misleading "RC down").

It exists because Claude Code's remote-control GUI context readout is unstable (a supervisor that
scrapes `Capacity: N/M` from a tmux pane has no per-worker token view). cc-monitor routes around
that by reading the authoritative local sources directly.

## What it reads (all local, read-only)

| Source | Provides |
|---|---|
| `~/.claude/sessions/<pid>.json` | session discovery + `busy`/`idle` status + `bridgeSessionId` (covers **both** cc-session `--resume` workers and RC env-spawned workers) |
| `~/.claude/projects/<slug>/<uuid>.jsonl` | model, token usage, context (input-side → unaffected by [#27361](https://github.com/anthropics/claude-code/issues/27361)), `custom-title`, initial prompt (opening turn, stable), last prompt (latest, volatile) |
| `/proc/<pid>/environ` | true context window (200k vs 1M) via the worker's `ANTHROPIC_DEFAULT_*_MODEL` `[1m]` default |
| `~/.claude/settings.json` | current reasoning `effortLevel` (global CLI setting; header only, `?` if unreadable) |
| `/tmp/cc-session/claude.prom` | **optional** cc-session supervisor health (header only; absent → standalone view) |

## Usage

```bash
cc-monitor once                  # text snapshot
cc-monitor html /tmp/dash.html   # self-refreshing HTML file
cc-monitor serve --port 8899     # localhost dashboard (127.0.0.1 only)
```

Install for **deploy** with pipx (`install/deploy.sh` does this); the runtime is stdlib-only.
For **development** — the host python often has no `pip` module — use a throwaway venv:

```bash
python3.14 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                 # run the suite
```

View a remote host's dashboard over SSH: `ssh -L 8899:127.0.0.1:8899 <host>`.

## HTTP API & metrics

The `serve` mode exposes, alongside the HTML dashboard:

| Route | Purpose |
|---|---|
| `GET /api/sessions` | current session rows as JSON (the same projection the SSE stream pushes) |
| `GET /api/stream` | Server-Sent Events — one `data:` frame per real change, heartbeats between |
| `GET /api/config` · `POST /api/config` | read / update the runtime config (schema-gated, persisted) |
| `GET /metrics` | Prometheus exposition — **aggregate** session gauges (see below) |

**Metrics** are aggregate, never per-session (a `session=<uuid>` label would be high-cardinality
and would leak session identity into the TSDB): `cc_monitor_sessions{status=...}`,
`cc_monitor_sessions_total`, `cc_monitor_context_tokens_sum`, `cc_monitor_context_pct_max`
(worst-case window utilisation — the thing worth alerting on), `cc_monitor_rc_connected`.
For the fleet, prefer the **textfile** path over scraping `/metrics`: set
`CC_MONITOR_METRICS_FILE` to a file under the Alloy textfile-collector dir and cc-monitor writes
it atomically each refresh (aligned with the fleet's textfile convention, not an HTTP scrape).
The file is written `0600` (owner-only); a system collector running as **root** reads it fine. A
non-root collector would need a wider mode — set that in the deploy that enables the export, where
the collector's uid/gid is known.

**Privacy** — set `redact_default: true` (via `POST /api/config` or the config file) to mask each
session's prompt **and** title to `[redacted]` server-side, across the HTML, text, and API/SSE
output. The real text never leaves the process (nothing to un-blur client-side); structural fields
(uuid, status, tokens) stay visible so the dashboard is still useful while redacted.

## Deploy (systemd --user)

```bash
cp install/.env.example install/.env   # set PORT / REFRESH / HOST
install/deploy.sh                       # idempotent: install pkg + unit, enable+start
```
The unit is resource-bounded (soft `MemoryHigh=256M` + hard `MemoryMax=512M`, `Nice=10`) so it
yields to co-tenant services on the host. A soft high-watermark drives gentle reclaim of the
reclaimable page cache from reading transcripts, rather than the reclaim storm a tight hard cap
would cause; no `CPUQuota`, since the parse cache makes steady-state work ~0 and the one-time cold
read must not be throttled into request timeouts.

**Bind (`HOST`)** defaults to `127.0.0.1`. To expose behind an edge reverse proxy over
Tailscale, set `HOST` to this host's tailscale0 IP — not `0.0.0.0`, so the raw port never
lands on the LAN. The dashboard has **no auth** (session prompts are rendered in the clear);
only bind a trusted interface and front it with a reverse proxy on a trusted network.

### Dev/staging instance

`install/deploy-dev.sh` stands up a second instance **alongside** prod for previewing WIP: it runs
the *current checkout* via an editable venv (restart to pick up commits), on `PORT_DEV` (default
8898) with an isolated config. Run it from a dedicated worktree so it tracks the preview branch:

```bash
git worktree add ../.wt/cc-monitor-dev <branch>
cd ../.wt/cc-monitor-dev && install/deploy-dev.sh   # -> cc-monitor-dev.service on :8898
```

## Known local limits (honest, by design)

- **Titles**: remote-control env-spawned sessions (the GUI's set) have no local `custom-title`
  — the real title is cloud-side. Shown as `— (cloud-side)`. Fill locally via a manual override
  file `~/.claude/cc-monitor-titles.json` (`{"<uuid|session_xxx>": "title"}`).
- **Window `?`**: if a worker's env is unreadable and usage never crossed 200k, the true
  window is locally unknowable (statusLine/OTel would resolve it). Flagged, not guessed.
- **Cumulative tokens** are a reference display, not a billing figure (`output_tokens`
  is undercounted upstream — #27361). Use `ccusage` for accounting.

## Response-time breakdown (P1)

TTFT / think / tool / wait breakdown needs OTel traces (`CLAUDE_CODE_ENABLE_TELEMETRY=1`
+ `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`); tracked separately from the P0 dashboard.
