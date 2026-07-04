# cc-monitor

Independent live dashboard for **Claude Code sessions** on a host running the
[cc-session](../cc-session/) supervisor and Claude Code remote-control. Shows, per session:
**model · token usage · context size (with true 200k/1M window) · running status**.

It exists because the remote-control GUI's context readout is unstable (the supervisor
scrapes `Capacity: N/M` from a tmux pane and has no per-worker token view). cc-monitor
routes around that by reading the authoritative local sources directly.

## What it reads (all local, read-only)

| Source | Provides |
|---|---|
| `~/.claude/sessions/<pid>.json` | session discovery + `busy`/`idle` status + `bridgeSessionId` (covers **both** cc-session `--resume` workers and RC env-spawned workers) |
| `~/.claude/projects/<slug>/<uuid>.jsonl` | model, token usage, context (input-side → unaffected by [#27361](https://github.com/anthropics/claude-code/issues/27361)), `custom-title`, last prompt |
| `/proc/<pid>/environ` | true context window (200k vs 1M) via the worker's `ANTHROPIC_DEFAULT_*_MODEL` `[1m]` default |
| `/tmp/cc-session/claude.prom` | cc-session supervisor health (header, display only) |

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
