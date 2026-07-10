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
| `~/.claude/sessions/<pid>.json` | session discovery (`pid`, `sessionId`, `procStart`, `cwd`, `name`) for **both** cc-session `--resume` workers and RC env-spawned workers. *Note: the status axis is **busy / active** — a session's presence in the registry means it has a reachable connection (Claude Code drops the entry when the session ends or disconnects), so a registered, reachable session is **active**, narrowed to **busy** while it is generating (a transcript write within `busy_idle_gap`). There is no time-based "idle" tier. `/proc` only validates process liveness (a defunct/zombie process → **orphaned**). Recent Claude Code versions dropped the `status`/`bridgeSessionId` fields this once read; a fresh registry `status: busy` is still honoured as a busy hint when present.* |
| `~/.claude/projects/<slug>/<uuid>.jsonl` | model, token usage, context (input-side → unaffected by [#27361](https://github.com/anthropics/claude-code/issues/27361)), `custom-title`, initial prompt (opening turn, stable), last prompt (latest, volatile) |
| `~/.claude/cc-monitor-statusline/<uuid>.json` | **true context window (200k vs 1M)** and per-session effort, captured from Claude Code's statusLine payload (`install/statusline-capture.sh`). The one local channel carrying the real window: the CLI appends the `[1m]` suffix at runtime from an account-level entitlement, so the transcript's model field, the OTel `api_request` event and `/proc` may all show a bare `claude-opus-4-8` for a 1M session. Only TUI sessions render a statusLine, so a sample is generalised to same-family sessions — see below |
| `/proc/<pid>/environ` | per-worker window **overrides**: an `ANTHROPIC_DEFAULT_*_MODEL` bearing `[1m]`, the `CLAUDE_CODE_DISABLE_1M_CONTEXT` kill switch, and `CLAUDE_CODE_MAX_CONTEXT_TOKENS` (honoured only when `DISABLE_COMPACT` is set or the model is not first-party — mirroring the CLI) |
| `~/.claude.json` | `additionalModelOptionsCache` only — fully-qualified model ids for families beyond the built-ins, used to resolve a family with no statusLine sample yet |
| `~/.claude/settings.json` | current reasoning `effortLevel` (global CLI setting; header only, `?` if unreadable); and the `env`-block window keys as a **fallback** beneath `/proc` — Claude Code applies them internally so they never reach `/proc/environ`. The fallback supplies the value but is marked certain only when the worker started at/after the settings mtime (else `?`, unless usage already proves the window) |
| `~/.claude/cc-monitor-otel.json` | **optional** per-session effort (`s-effort` column) — an OTel rollup sidecar written by the embedded OTLP sink (see below). Preferred over the statusLine sample: it reflects the effort a request actually ran at. Absent → falls back to statusLine, else blank |
| `/tmp/cc-session/claude.prom` | **optional** cc-session supervisor health (header only; absent → standalone view) |

### Context window (statusLine calibration)

Claude Code does not persist the context window anywhere a monitor can read. It decides at runtime
whether to append `[1m]` to the model id, from an entitlement predicate that depends on the account
(plan tier, provider, the `CLAUDE_CODE_DISABLE_1M_CONTEXT` env). A 1M session therefore writes a
bare `claude-opus-4-8` into its transcript and exports the same bare id on its OTel `api_request`
event, while `/proc/<pid>/environ` may carry no model keys at all.

The single exception is the **statusLine payload**, which hands the command
`context_window.context_window_size` and a suffixed `model.id`. `install/statusline-capture.sh`
persists those scalars per session; `deploy.sh` wires it (and leaves an existing statusLine alone —
chain it via `CC_MONITOR_STATUSLINE_CHAIN`).

Only TUI sessions render a statusLine, and on a cc-session fleet most sessions are `sdk-cli`
workers that never do. Since the entitlement predicate is **account-level, not per-session**, one
sample generalises: an Opus sample resolves every Opus session on the box. Resolution order, first
hit wins:

1. **worker env** — `[1m]` default, kill switch, or an honoured ceiling. Per-worker, so it outranks
   any account-level inference (this is what makes the generalisation sound).
2. **statusLine sample for this exact `session_id`** — direct observation.
3. **statusLine sample for the same model family** — the calibration; latest sample wins.
4. **`additionalModelOptionsCache`** — supplies a value; certain only once some sample has proven
   the account really receives `[1m]`.
5. **settings.json `env` block** — value freely, certainty only for workers started under it.
6. **peak context** — a hard lower bound: usage above the resolved window proves 1M regardless.

Nothing decides → `?`. A readable env with no model keys is **not** evidence of 200k.

> **Boundary.** The generalisation assumes one account on one host — cc-monitor's stated scope. Two
> accounts sharing a `~/.claude`, or a per-worker entitlement that `/proc` cannot show, would break
> it. A worker's own `CLAUDE_CODE_DISABLE_1M_CONTEXT` is read from `/proc` and does override.

### Per-session effort (embedded OTel sink)

`effortLevel` above is the **global** CLI setting. Each session's *own* effort (which can differ, and change mid-run) is not in any local file — the only source is Claude Code's own OTel telemetry ([docs](https://code.claude.com/docs/en/monitoring-usage)). When `cc-monitor serve` runs, it starts a loopback OTLP/HTTP receiver (`127.0.0.1:4318`, `--no-otel-sink` to disable) that reads the `api_request` log event (`effort` + cost/tokens/duration, keyed by `session.id`), strips identity attributes, and rolls up to the sidecar above (`0600`). It's a passive in-process side-channel — **no Anthropic auth, no extra API call, no token cost**. Enable telemetry in `settings.json` so every spawn path (RC / `--resume` / GUI) exports:

```json
{ "env": { "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_LOGS_EXPORTER": "otlp",
           "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
           "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318" } }
```

Per-session detail stays in the sidecar, **never** in Prometheus (`session.id` is a high-cardinality label). Without telemetry the `s-effort` column is blank and everything else is unchanged.

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

> **Python 3.14 required.** The package pins `requires-python = ">=3.14"` — it
> targets the free-threaded (`3.14t`) build for the concurrent refresh/collect
> loop. There is no PyPI package yet; install from source. On 3.12/3.13 the
> install fails fast at the `requires-python` gate.

View a remote host's dashboard over SSH: `ssh -L 8899:127.0.0.1:8899 <host>`.

## HTTP API & metrics

The `serve` mode exposes, alongside the HTML dashboard:

| Route | Purpose |
|---|---|
| `GET /api/sessions` | current session rows as JSON (the same projection the SSE stream pushes) |
| `GET /api/stream` | Server-Sent Events — one `data:` frame per real change, heartbeats between |
| `GET /api/config` · `POST /api/config` | read / update the runtime config (schema-gated, persisted) |
| `POST /api/titles` | set/clear a local title override — `{key: sessionId\|bridgeSessionId, title}` (empty title clears); atomic write |
| `GET /metrics` | Prometheus exposition — **aggregate** session gauges (see below) |

The dashboard at `/` is a zero-horizontal-scroll SPA: any viewport shows 5 importance-ordered
fields (status → name → latest prompt → context → idle); origin, bridge, model, cum tokens and the
opening prompt drill down into an expand panel. Three density presets (patrol / standard / debug),
a settings drawer (reveal · theme · prompt line-clamp · ctx thresholds · columns), and in-place
rename (writing back via `POST /api/titles`). Prompt summaries truncate by visual line count (CSS
line-clamp), so CJK reads as a first-class script. Display prefs persist in `localStorage`; reveal
is a server behaviour switch (`redact_default`), single-user with no per-device auth. `/legacy`
still serves the no-JS `<meta refresh>` fallback for curl.

**Metrics** are aggregate, never per-session (a `session=<uuid>` label would be high-cardinality
and would leak session identity into the TSDB): `cc_monitor_sessions{status=...}`,
`cc_monitor_sessions_total`, `cc_monitor_context_tokens_sum`, `cc_monitor_context_pct_max`
(worst-case window utilisation — the thing worth alerting on), `cc_monitor_rc_connected`.
For the fleet, prefer the **textfile** path over scraping `/metrics`: set
`CC_MONITOR_METRICS_FILE` to a file under the Alloy textfile-collector dir and cc-monitor writes
it atomically each refresh (aligned with the fleet's textfile convention, not an HTTP scrape).
The unit pins `UMask=0022`, so the `.prom` lands world-readable `0644` — a node-exporter / Alloy
textfile collector (typically running as `nobody`) reads it off disk. This is distinct from the
per-session OTel **sidecar** (`~/.claude/cc-monitor-otel.json`), which is `0600` because it holds
per-session cost.

### Runtime config

`serve` reads a schema-gated config each refresh, so edits apply live (no restart).
Precedence: built-in defaults ← `~/.claude/cc-monitor-config.json` (written by `POST /api/config`)
← env var (ops escape hatch) ← per-invocation CLI flag (e.g. `--redact`, not persisted). Writes are
clamped to range, coerced to type, and atomic; a corrupt file falls back to defaults rather than
crashing a render.

| Key | Default | Range | Effect |
|---|---|---|---|
| `busy_idle_gap` | `12` | 1–3600 | seconds of transcript silence before a session flips from `busy` to `active` (env: `CC_MONITOR_BUSY_IDLE_GAP`) |
| `ctx_warn_pct` | `50` | 0–100 | context-usage colour turns amber above this |
| `ctx_crit_pct` | `80` | 0–100 | context-usage colour turns red above this |
| `title_trunc_text` / `prompt_trunc_text` | `22` / `40` | 4–512 | text-mode truncation widths |
| `title_trunc_html` / `prompt_trunc_html` | `48` / `70` | 4–512 | HTML-mode truncation widths |
| `redact_default` | `true` | — | mask each session's prompt + title server-side — safe-by-default (see Privacy) |

**Privacy** — redaction is **on by default** (`redact_default: true`): each session's prompt **and**
title is masked to `[redacted]` server-side, across the HTML, text, and API/SSE output. The real
text never leaves the process (nothing to un-blur client-side); structural fields (uuid, status,
tokens) stay visible so the dashboard is still useful while redacted.

Disable it per invocation with `--no-redact` on `once` / `html` / `serve` (or force it on with
`--redact`), or persistently by setting `redact_default: false`. The CLI flag is not persisted and
outranks the config file. `cc-monitor --version` prints the version.

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
- **Window `?`**: no statusLine sample for this session or its model family, no `[1m]` in the
  worker env, and usage never crossed 200k — the window is not locally knowable. Flagged, not
  guessed. Run `install/deploy.sh` to wire the statusLine capture, then open any TUI session of
  that family once; every session of that family resolves from then on.
- **Cumulative tokens** are a reference display, not a billing figure (`output_tokens`
  is undercounted upstream — #27361). Use `ccusage` for accounting.

## Response-time breakdown (P1)

TTFT / think / tool / wait breakdown needs OTel traces (`CLAUDE_CODE_ENABLE_TELEMETRY=1`
+ `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`); tracked separately from the P0 dashboard.
