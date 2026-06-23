# EDD — RC cold-boot resilience hardening

Status: **Draft** · Driver: homelab-ops#1222 (rpi RC backbone DR drill **FAILED**)
Scope: `cc-session` supervisor (A startup gate · B non-terminal backoff + monitoring · D real health probe)
Out of scope: C credential exclusivity — **closed**, ccrc now holds its own (post-rotation) refresh token at `~/.claude/.credentials.json`.

## 1. Problem

Cold boot of the rpi RC backbone leaves `claude remote-control` permanently
down; teleport is dead until manual intervention. Reproduced deterministically
during the homelab-ops#1222 cold-boot DR drill.

### Observed failure (rpi, boot 2026-06-22 19:03)

```
attempt 1  Error: ECONNREFUSED                         # network/tailscale not up yet
attempt 2  Error: Registration: Authentication failed (401):
           Invalid authentication credentials. Remote Control is only
           available with claude.ai subscriptions.     # stale access token
attempt 3-5  (same 401)
19:04:59   CIRCUIT BREAKER: 5 consecutive failures — stopping
           → supervisor exits rc=0 → tmux pane dead → no RC daemon
19:08      an interactive `claude` (operator debug login) refreshed the
           access token (rewrote .credentials.json); RC then connects fine
```

### Root cause chain

1. **Trigger — stale access token at boot.** On cold boot the cached access
   token is expired. `claude remote-control` does **not** pre-refresh; it
   registers with the stale token and gets 401. (Upstream:
   anthropics/claude-code#34306 "OAuth token not auto-refreshed on startup",
   #61551 "RC fails at registration 401 despite valid Max".)
2. **Amplifier #1 — terminal circuit breaker.** The cold-boot
   network/cred-not-ready window (ECONNREFUSED + early 401s, all < 60 s) is
   counted as 5 consecutive failures → supervisor `break`s and exits **rc=0**.
   A transient becomes a permanent outage. `Restart=on-failure` never fires
   because the exit is clean (this trap was previously recorded for the
   servarica bastion: RC self-exits status 0 → needs `Restart=always`).
3. **Amplifier #2 — false-positive health signals.**
   - The pre-respawn probe `claude auth status` reports `loggedIn: true` even
     when the access token is expired (it is a local-only check; upstream
     docs + #34306). It gave "auth probe OK" while RC 401'd.
   - `systemctl --user is-active cc-session` = `active` while the pane is
     dead (Type=forking + tmux server outlives the supervisor process).
   - `--ctl health` reports `pid: none` even when the RC child is alive,
     because the watchdog subshell cannot see the parent's `child` var.

### Why C is not the fix here
Refresh tokens rotate / are single-use with token-family invalidation
(anthropics/claude-code#54443). The bring-up shared ubuntu's credential, so a
refresh on either side invalidated the other → 401 for the loser. As of
2026-06-22 ccrc holds its own freshly-rotated refresh token and there is no
live ubuntu consumer; treat ccrc as the sole consumer going forward. No code
change required for C.

## 2. Goals / non-goals

**Goals**
- A cold-boot transient (network-not-ready and/or stale token) must
  **self-heal** within a bounded time, never latch the backbone off.
- Health/metrics must reflect **real RC connectivity**, not local cred state.
- Monitoring stack can alert on a down/flapping backbone.

**Non-goals**
- Implementing a credential force-refresh primitive (no such CLI exists —
  #34306/#Q4). We work around its absence.
- Multi-account credential isolation (C; closed).

## 3. Design

### A — startup gate (token freshness before RC)

There is **no** documented force-refresh command; `auth status`, `-p`, and
`setup-token` do not deterministically refresh (research low-confidence).
Empirically a *full* `claude` process refreshed the token at 19:08, whereas
`claude remote-control` alone did not.

Gate (runs before the first `remote-control` launch, and is cheap to repeat):
1. Already present: unit `After=network-online.target tailscaled.service`.
   Add an explicit reachability wait (poll a claude.ai/API endpoint or
   `tailscale status` until up, bounded ~60 s) so attempt 1 is not wasted on
   ECONNREFUSED.
2. **Refresh trigger:** run one headless `claude -p` ping (minimal prompt,
   `--max-turns 1`) to force the on-401 auto-refresh that rewrites
   `.credentials.json`, then launch `remote-control`.

> **OPEN QUESTION (must validate before merge):** does a headless `claude -p`
> reliably trigger the refresh? Research is low-confidence and it could not be
> tested live (token was fresh). **Validation plan:** force an expired access
> token (or wait for natural expiry), run `claude -p`, assert
> `.credentials.json` mtime advances and a subsequent `remote-control`
> connects. If `-p` does **not** refresh, A degrades to "rely on B" (the gate
> becomes best-effort and B guarantees eventual recovery).

A is therefore an **optimization** (faster first-attempt success). Correctness
is guaranteed by B.

### B — non-terminal backoff + monitoring

- **Remove the terminal break.** After `CC_SESSION_SV_MAX_FAILS` consecutive
  sub-`stable` failures, do **not** exit. Instead enter a long-backoff steady
  state: sleep `CC_SESSION_SV_BACKOFF_MAX` (default 60 s) and keep retrying
  indefinitely, incrementing `respawn_total`. The circuit "breaker" becomes a
  rate limiter, not a kill switch.
  - Keep a distinct `cc_session_circuit_open` gauge (1 while in long-backoff)
    so monitoring can tell "degraded but trying" from "healthy".
- **Belt-and-suspenders:** unit `Restart=always` (with existing
  `StartLimitIntervalSec=600`/`StartLimitBurst=5` as the real upper bound) so
  even a supervisor crash respawns. Clean rc=0 exits no longer strand the
  backbone.
- **Monitoring (homelab-ops side, tracked separately):** scrape
  `/tmp/cc-session/claude.prom` (textfile collector via node_exporter, or a
  small pushgateway job) → Alertmanager rules:
  `cc_session_up == 0` for 5m · `cc_session_circuit_open == 1` for 10m ·
  `rate(cc_session_respawn_total[15m])` spike. Beszel is display-only; alerting
  goes through Prometheus + Alertmanager.

### D — real health probe

Replace the local-only `claude auth status` probe with an RC-connectivity
signal derived from the pane the daemon already prints to:

- `auth_healthy` / `up` ← `tmux capture-pane | grep -q '✔︎· Connected'`
  (the daemon prints `·✔︎· Connected` on success, reconnect text on drop).
- Capture and export the live `env_<id>` (and `Capacity n/32`) into
  `claude.health` / `claude.prom` as `cc_session_rc_env` /
  `cc_session_capacity`.
- Fix `pid` reporting: the watchdog subshell must read the child pid from a
  shared file/var, not the unset `child` local (currently always `none`).
- `is-active` accuracy: prefer the pane-liveness signal in metrics; the
  systemd `Type=forking` limitation is documented but `cc_session_up` is the
  source of truth.

## 4. Verification

1. Unit / dummy-harness tests under `tests/` (bats, `env -u TMUX`): simulate
   N early failures → assert supervisor keeps retrying (no exit) and metrics
   show `circuit_open=1`.
2. **A validation** (open question above) — expired-token refresh experiment.
3. **DR drill** (operator-gated, homelab-ops#1222 close criterion): cold boot
   → assert within ~2 min `cc_session_up=1`, RC Connected, no manual step.

## 5. Rollout

- PR to Jarvie8176/tools (cc-session). Bump patch version; regenerate the
  inline supervisor.
- Redeploy on rpi: `cc-session --update` / re-symlink, `systemctl --user
  daemon-reload && restart`. (Deployed `/usr/local/bin/cc-session` is a
  symlink to this repo, so a pull suffices once merged.)
- Update homelab-ops#1222 with DR-drill result; wire monitoring under the
  monitoring topology SoT.
