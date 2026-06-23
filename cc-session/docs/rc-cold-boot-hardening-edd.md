# EDD — RC cold-boot resilience hardening

Status: **Draft** · Driver: homelab-ops#1222 (rpi RC backbone DR drill **FAILED**)
Scope: `cc-session` supervisor + teleport/resume paths
(A startup gate · B non-terminal backoff + monitoring · D real health probe +
file-backed state · E impl-review defects: #1 CLAUDE_BIN, #5 send-keys, N4 SIGTERM)
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

### D — real health probe + file-backed supervisor state

**Root cause uncovered by impl review (N1, fork-by-value):** the supervisor
shares `child` / `auth_healthy` / `respawn_total` / `last_error_epoch` across
THREE processes (main loop + watchdog `&` + ctl_reader `&`) via plain shell
vars. `&` forks copy-by-value, so the subshells never see the parent's
assignments. This single wrong abstraction simultaneously breaks:
- **`pid: none`** — the watchdog snapshotted `child=""` at fork (the original
  defect #4).
- **`--ctl respawn` / `--ctl stop` are no-ops** (N2) — ctl_reader tests `$child`
  (always empty) → it cannot kill the running claude; `stop` only takes effect
  after claude exits on its own.
- **`respawn_total` flaps to 0** — the watchdog's `write_prom` writes its stale
  snapshot over the parent's real counter via the atomic `mv`.

**Fix = make shared supervisor state file-backed (single source of truth):**
- Write the live child pid and the counters to small files under
  `$state_dir` on each spawn/exit; watchdog + ctl_reader + `write_health` /
  `write_prom` READ from those files, never from in-memory vars. This resolves
  #4, N1, and N2 together and makes B/D compose cleanly.

**Health signal (replaces the false-positive `auth status` probe, #3):**
- `auth_healthy` / `up` ← `tmux capture-pane | grep -q '✔︎· Connected'`
  (daemon prints `·✔︎· Connected` on success, reconnect text on drop).
  Demote `claude auth status` to a secondary cred-state field, not the up signal.
- Capture and export the live `env_<id>` (and `Capacity n/32`) into
  `claude.health` / `claude.prom` as `cc_session_rc_env` / `cc_session_capacity`.
- `is-active` accuracy: `cc_session_up` (pane liveness) is the source of truth;
  the systemd `Type=forking` mismatch is documented, not relied upon.

### E — additional defects (from impl review, not in original draft)

- **#1 `CLAUDE_BIN` unbound (ordering).** `$CLAUDE_BIN` is dereferenced in the
  default-`SESSION_NAME` block (~line 1313) before the resolver runs (~1328).
  Under `set -u`, with `CLAUDE_BIN` unset (the normal case — templates leave it
  commented), every name-auto-deriving invocation (incl. `--teleport` /
  `--resume`) leaks `CLAUDE_BIN: unbound variable` to stderr (reproduced twice
  during the session-recovery work). Fix: relocate the resolver above line 1305.
- **#5 send-keys idle-readiness.** After the resume-choice keypress the
  readiness gate is a hard-coded `sleep 2` before `enable_remote_control`, which
  then polls only ~10 s. A 6.4 MB transcript took ~5 min to load → `/remote-control`
  fired into the still-loading TUI, landing in the autocomplete menu /
  mis-submitted (observed live; corrupted one recovered turn). Fix: poll for an
  idle-prompt marker before sending; scale the wait with the resume timeout;
  raise the teleport/resume `enable_remote_control` poll ceiling.
- **N4 SIGTERM trap.** The supervisor only `trap`s EXIT (kills watchdog/ctl,
  not the claude child). `systemctl stop` / `Restart` SIGTERM can orphan the
  claude process; only `ExecStop=cc-session --kill` reaps it. Add
  `trap 'kill "$child"…; cleanup' TERM INT` (child read from the state file).
- **N3 `$TMUX` nesting guard (Lo).** `exec tmux attach` from inside an existing
  tmux refuses; guard with `[[ -n "$TMUX" ]]` → `switch-client` / print hint.

## 4. Verification

1. Unit / dummy-harness tests under `tests/` (bats, `env -u TMUX`):
   - supervisor keeps retrying after `MAX_FAILS` (no exit) + `circuit_open=1` (B).
   - `pid:` is a real PID and `respawn_total` is non-zero/stable across a
     watchdog interval (regression guard for N1).
   - `--ctl respawn`/`stop` actually kill the child (N2), not just log.
   - `env -u CLAUDE_BIN` invocation produces no stderr (#1).
   - slow-transcript fixture → `/remote-control` lands at an idle prompt (#5).
2. **A validation** (open question above) — expired-token refresh experiment.
3. **DR drill** (operator-gated, homelab-ops#1222 close criterion): cold boot
   → assert within ~2 min `cc_session_up=1`, RC Connected, no manual step.

## 5. Prioritized fix list (single PR)

- **P0 (cold-boot availability):** #2 non-terminal breaker + `Restart=always` ·
  #3 real RC probe · **N1 file-backed state** (fixes #4 pid + N2 dead IPC) ·
  #1 CLAUDE_BIN ordering.
- **P1 (robustness):** #5 send-keys idle-readiness · N4 SIGTERM trap ·
  §A startup gate (optional, gated on the `claude -p` refresh validation).
- **P2 (hygiene):** N3 `$TMUX` guard · tests above · bash-3.2 CI leg.

Verdict (impl review): architecture is **sound — patch, don't rewrite**. The
CLI/state-machine layer stays; only the supervisor's shared-state model is
reworked (file-backed). Extracting the inline heredoc into a shipped
`cc-session __supervise` sub-script is a sensible **follow-up**, not this PR.

## 6. Rollout

- PR to Jarvie8176/tools (cc-session). Bump patch version; regenerate the
  inline supervisor.
- Redeploy on rpi: `cc-session --update` / re-symlink, `systemctl --user
  daemon-reload && restart`. (Deployed `/usr/local/bin/cc-session` is a
  symlink to this repo, so a pull suffices once merged.)
- Update homelab-ops#1222 with DR-drill result; wire monitoring under the
  monitoring topology SoT.
