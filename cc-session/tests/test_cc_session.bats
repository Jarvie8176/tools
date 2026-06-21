#!/usr/bin/env bats
#
# Black-box tests for cc-session. Every test invokes cc-session as a
# subprocess. claude is stubbed with tests/fixtures/fake-claude so we
# never touch the real CLI, the cloud, or anything network-bound.
#
# Important note on bats + `[[ ]]`: a non-final `[[ ... ]]` that is
# false does NOT fail the test (only the last command's exit status
# determines pass/fail). All assertions in this file go through
# `assert_*` / `refute_*` helpers below, which return non-zero on
# mismatch and produce a useful diagnostic.

setup() {
  CC_SESSION="${BATS_TEST_DIRNAME}/../cc-session"
  FAKE_CLAUDE="${BATS_TEST_DIRNAME}/fixtures/fake-claude"
  chmod +x "$FAKE_CLAUDE" "$CC_SESSION"

  TEST_DIR="${BATS_TMPDIR}/cc-session-test-$$-${BATS_TEST_NUMBER}"
  mkdir -p "$TEST_DIR"

  SESSION_NAME="cc-test-$$-${BATS_TEST_NUMBER}"

  export CLAUDE_BIN="$FAKE_CLAUDE"
  # Isolate this test run's tmux server and TMPDIR-based state so we
  # don't collide with the host's tmux or any prior cc-session run.
  export TMUX_TMPDIR="${BATS_TMPDIR}/cc-session-tmux-$$"
  export TMPDIR="${BATS_TMPDIR}"
  mkdir -p "$TMUX_TMPDIR"

  # Isolate lever ⑤ audit writes per test (never touch ~/.local/state).
  export CC_SESSION_AUDIT_FILE="${TEST_DIR}/audit.jsonl"
  # Disable the lever ④ reaper by default so the long-lived teleport
  # tests don't each spawn a background poll loop / write reap records.
  # The dedicated reaper tests opt back in with CC_SESSION_NO_REAP=0.
  export CC_SESSION_NO_REAP=1
}

teardown() {
  tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
  # Lever ① auto-named teleport sessions (claude-tp-<id8>-<hex>) and
  # C3 auto-named default sessions (cc-YYYYMMDD-*) have dynamic names;
  # sweep them. Safe — the tmux server is isolated to this bats run
  # via TMUX_TMPDIR.
  for _s in $(tmux list-sessions -F '#{session_name}' 2>/dev/null \
                | grep -E "^claude-tp-|^cc-[0-9]{8}-|$SESSION_NAME" || true); do
    tmux kill-session -t "$_s" 2>/dev/null || true
  done
  rm -rf "$TEST_DIR" \
         "${BATS_TMPDIR}/cc-session/$SESSION_NAME.url" \
         "${BATS_TMPDIR}/cc-session/$SESSION_NAME.health" \
         "${BATS_TMPDIR}/cc-session/$SESSION_NAME.prom" \
         "${BATS_TMPDIR}/cc-session/cc-"*.url \
         "${BATS_TMPDIR}/cc-session/cc-"*.health \
         "${BATS_TMPDIR}/cc-session/cc-"*.prom
  # Clean up named pipes.
  for _p in "${BATS_TMPDIR}/cc-session/$SESSION_NAME.ctl" \
            "${BATS_TMPDIR}"/cc-session/cc-*.ctl; do
    [ -p "$_p" ] && rm -f "$_p" 2>/dev/null || true
  done
}

# --- Assertion helpers (non-final-line safe) -------------------------

assert_eq() {
  if [ "$1" != "$2" ]; then
    printf 'ASSERT_EQ failed: expected %q got %q\n' "$2" "$1" >&2
    return 1
  fi
}

assert_contains() {
  if [[ "$1" != *"$2"* ]]; then
    printf 'ASSERT_CONTAINS failed:\n  haystack: %q\n  needle:   %q\n' "$1" "$2" >&2
    return 1
  fi
}

refute_contains() {
  if [[ "$1" == *"$2"* ]]; then
    printf 'REFUTE_CONTAINS failed:\n  haystack: %q\n  needle:   %q (unexpectedly present)\n' "$1" "$2" >&2
    return 1
  fi
}

# --- Pane-content helpers -------------------------------------------

# Read the "fake claude args: ..." line from a session's first pane.
pane_args() {
  local sess="$1"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    out="$(tmux capture-pane -t "$sess" -p 2>/dev/null | grep '^fake claude args:' || true)"
    [ -n "$out" ] && { printf '%s\n' "$out"; return 0; }
    sleep 0.1
  done
  return 1
}

# Wait up to ~30s for a substring to appear in a session's pane.
# Returns 0 if found, 1 on timeout.
wait_for_pane() {
  local sess="$1" needle="$2" tries="${3:-60}"
  for _ in $(seq 1 "$tries"); do
    if tmux capture-pane -t "$sess" -p -S -200 2>/dev/null | grep -q -F "$needle"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

marker_value() {
  tmux show-options -t "$1" -v '@cc-session-managed' 2>/dev/null || true
}

mode_value() {
  tmux show-options -t "$1" -v '@cc-session-mode' 2>/dev/null || true
}

# Exact-name existence (mirrors cc-session's sess_exists): tmux's own
# `has-session -t name` would prefix-match, so grep the session list
# for an exact line instead.
has_exact() {
  tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -qxF -- "$1"
}

# Find the auto-allocated claude-tp-<id8>-<hex> session for a given id8.
autoname_for() {
  tmux list-sessions -F '#{session_name}' 2>/dev/null \
    | grep -E "^claude-tp-$1-[0-9a-f]{6}\$" | head -1 || true
}

# --- usage / help ----------------------------------------------------

@test "--help renders and exits 0 with all sections" {
  run "$CC_SESSION" --help
  assert_eq "$status" 0
  assert_contains "$output" NAME
  assert_contains "$output" SYNOPSIS
  assert_contains "$output" -- --teleport
  assert_contains "$output" -- --resume
  assert_contains "$output" -- --full
  assert_contains "$output" -- --compact
  assert_contains "$output" -- --adopt
  assert_contains "$output" "@cc-session-managed"
  assert_contains "$output" CC_SESSION_SKIP_FULL_CONFIRM
  assert_contains "$output" CC_SESSION_RESUME_TIMEOUT
  assert_contains "$output" CC_SESSION_RC_URL_TIMEOUT
  assert_contains "$output" CC_SESSION_RC_ENABLE_TIMEOUT
  assert_contains "$output" -- --update
  assert_contains "$output" CC_SESSION_UPDATE_URL
}

@test "-h is an alias for --help" {
  run "$CC_SESSION" -h
  assert_eq "$status" 0
  assert_contains "$output" NAME
}

@test "unknown flag exits 2 with hint" {
  run "$CC_SESSION" --bogus
  assert_eq "$status" 2
  assert_contains "$output" "unknown option: --bogus"
  assert_contains "$output" "Try"
}

@test "--version prints program name + semver" {
  run "$CC_SESSION" --version
  assert_eq "$status" 0
  # Output looks like: "cc-session 0.2.0"
  [[ "$output" =~ ^cc-session\ [0-9]+\.[0-9]+\.[0-9]+$ ]]
}

@test "-v is an alias for --version" {
  run "$CC_SESSION" -v
  assert_eq "$status" 0
  assert_contains "$output" "cc-session"
}

# --- --kill scaffolding ---------------------------------------------

@test "--kill without a name exits 2" {
  run "$CC_SESSION" --kill
  assert_eq "$status" 2
  assert_contains "$output" -- "--kill requires a session name"
}

@test "--kill removes the state .url file (stale URL hygiene)" {
  # Create a session, wait for state file to appear, then --kill and
  # confirm both the tmux session and the state file are gone.
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]

  run "$CC_SESSION" --kill "$SESSION_NAME"
  assert_eq "$status" 0
  [ ! -f "$state_file" ]
  run tmux has-session -t "$SESSION_NAME"
  refute_contains "$status" 0
}

@test "--kill on a never-existed session still cleans state file (best effort)" {
  # Plant a stale state file from some prior cc-session that crashed.
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  mkdir -p "$(dirname "$state_file")"
  printf 'https://claude.ai/code/session_OBSOLETE12345\n' > "$state_file"

  # No tmux session of this name exists. --kill should fail (tmux exit
  # 1) but still wipe the state file.
  run "$CC_SESSION" --kill "$SESSION_NAME"
  refute_contains "$status" 0
  [ ! -f "$state_file" ]
}

# --- --status -------------------------------------------------------

@test "--status on a live managed session: alive=yes, url present, uptime>0" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Wait for state file (URL captured).
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]
  sleep 1  # ensure uptime_seconds is non-zero

  run "$CC_SESSION" --status "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "session: $SESSION_NAME"
  assert_contains "$output" "alive: yes"
  assert_contains "$output" "managed: yes"
  assert_contains "$output" "https://claude.ai/code?environment=env_FAKE"
  # uptime_seconds: <int> with int >= 0
  [[ "$output" =~ uptime_seconds:\ ([0-9]+) ]] && [ "${BASH_REMATCH[1]}" -ge 0 ]
}

@test "--status on a nonexistent session: alive=no, exit 1" {
  run "$CC_SESSION" --status "definitely-not-here-$$"
  assert_eq "$status" 1
  assert_contains "$output" "alive: no"
  assert_contains "$output" "managed: no"
}

@test "--status surfaces stale state file even when tmux session is gone" {
  # Plant a stale state file from some prior cc-session run.
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  mkdir -p "$(dirname "$state_file")"
  printf 'https://claude.ai/code/session_STALE12345\n' > "$state_file"

  run "$CC_SESSION" --status "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "alive: no"
  # url field still emits the stale URL — caller can spot the staleness
  # because alive=no.
  assert_contains "$output" "session_STALE12345"
}

@test "--status with no arg lists every managed session, exits 0 if any alive" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  sleep 1

  run "$CC_SESSION" --status
  assert_eq "$status" 0
  assert_contains "$output" "session: $SESSION_NAME"
  assert_contains "$output" "alive: yes"
}

@test "--status with no arg + no managed sessions exits 1 with 'no managed' message" {
  # Pre-create an UNMANAGED tmux session so it's filtered out.
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "sleep 3600"
  run "$CC_SESSION" --status
  assert_eq "$status" 1
  assert_contains "$output" "no managed sessions"
  refute_contains "$output" "session: $SESSION_NAME"
}

@test "remain-on-exit preserves crashed pane buffer and --status reports alive=no" {
  # Launch with a claude stub that exits immediately. Without
  # remain-on-exit the pane would be destroyed and its scrollback wiped
  # — making the crash undebuggable. With the option the pane stays
  # with pane_dead=1, scrollback intact, and --status flips alive→no.
  # SV_MAX_FAILS=1 + SV_BACKOFF_BASE=1 so the supervisor circuit-breaks
  # immediately after the single crash and the pane dies quickly.
  CC_FAKE_CLAUDE_CRASH=1 \
    CC_SESSION_RC_URL_TIMEOUT=2 \
    CC_SESSION_SV_MAX_FAILS=1 \
    CC_SESSION_SV_BACKOFF_BASE=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0

  # Wait for the stub to exit and the background URL-poll to notice.
  # The early-exit branch should fire within ~0.5s once pane_dead=1.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pd="$(tmux list-panes -s -t "$SESSION_NAME" -F '#{pane_dead}' 2>/dev/null | head -1 || true)"
    [ "$pd" = "1" ] && break
    sleep 0.3
  done
  assert_eq "$pd" "1"

  # Crash output (stdout AND stderr) must still be capturable.
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200 2>/dev/null)"
  assert_contains "$buf" "FAKE CLAUDE: crashing on purpose"
  assert_contains "$buf" "FAKE CLAUDE: stderr line"

  # --status must report alive=no even though tmux has-session=true.
  run "$CC_SESSION" --status "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "alive: no"
  assert_contains "$output" "managed: yes"
}

@test "remain-on-exit is set as a window option on newly created sessions" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  opt="$(tmux show-window-options -t "$SESSION_NAME" -v remain-on-exit 2>/dev/null || true)"
  assert_eq "$opt" "on"
}

@test "state file written via tmpfile-then-rename (atomic)" {
  # Spawn a session, wait for state to land, then verify no .tmp.* file
  # was left behind in the state dir (would indicate an interrupted write).
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]
  # No leftover tmpfiles
  leftover=$(find "$(dirname "$state_file")" -maxdepth 1 -name "$SESSION_NAME.url.tmp.*" 2>/dev/null | wc -l | tr -d ' ')
  assert_eq "$leftover" "0"
}

# --- --worktree -----------------------------------------------------

@test "--worktree without a name exits 2" {
  run "$CC_SESSION" --worktree
  assert_eq "$status" 2
  assert_contains "$output" -- "--worktree requires a name"
}

@test "--worktree refuses 'main' (and other protected refs)" {
  for name in main master origin/main origin/master; do
    run "$CC_SESSION" --worktree "$name" "$TEST_DIR" "$SESSION_NAME"
    assert_eq "$status" 2
    assert_contains "$output" "refusing to create worktree on '$name'"
  done
}

@test "--worktree on a non-git PROJECT_DIR exits 1" {
  run "$CC_SESSION" --worktree foo "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" -- "--worktree requires PROJECT_DIR to be a git repo"
}

@test "--worktree on a real git repo creates branch + path + launches claude" {
  # Build a tiny throwaway repo with an 'origin/main' to base off.
  upstream="${TEST_DIR}/upstream.git"
  workrepo="${TEST_DIR}/work"
  git init --bare -q "$upstream"
  git init -q -b main "$workrepo"
  git -C "$workrepo" remote add origin "$upstream"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m init
  git -C "$workrepo" push -q origin main

  run "$CC_SESSION" -d -w ops/foo "$workrepo" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "worktree ready"

  wt="${TEST_DIR}/work-wt/foo"
  [ -d "$wt" ] || { echo "expected worktree dir: $wt"; return 1; }
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD)"
  assert_eq "$branch" "ops/foo"

  # Cleanup: tmux teardown is handled by the per-test teardown.
}

@test "--worktree refuses a path that already exists" {
  upstream="${TEST_DIR}/upstream.git"
  workrepo="${TEST_DIR}/work"
  git init --bare -q "$upstream"
  git init -q -b main "$workrepo"
  git -C "$workrepo" remote add origin "$upstream"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m init
  git -C "$workrepo" push -q origin main

  # First call succeeds.
  run "$CC_SESSION" -d -w ops/foo "$workrepo" "${SESSION_NAME}-a"
  assert_eq "$status" 0

  # Second call with same NAME must error before touching anything.
  run "$CC_SESSION" -d -w ops/foo "$workrepo" "${SESSION_NAME}-b"
  assert_eq "$status" 1
  assert_contains "$output" "worktree path already exists"
  assert_contains "$output" "git worktree remove"
}

@test "hint fires when PROJECT_DIR is a git repo on a non-main branch" {
  workrepo="${TEST_DIR}/work"
  git init -q -b main "$workrepo"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m init
  git -C "$workrepo" checkout -q -b ops/leftover

  run "$CC_SESSION" -d "$workrepo" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "hint"
  assert_contains "$output" "branch 'ops/leftover'"
  assert_contains "$output" "-w ops/<task>"
  assert_contains "$output" "checkout main"
}

@test "hint is silent when PROJECT_DIR is on main" {
  workrepo="${TEST_DIR}/work"
  git init -q -b main "$workrepo"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m init

  run "$CC_SESSION" -d "$workrepo" "$SESSION_NAME"
  assert_eq "$status" 0
  refute_contains "$output" "hint"
}

@test "hint is suppressed by CC_SESSION_NO_WORKTREE_HINT=1" {
  workrepo="${TEST_DIR}/work"
  git init -q -b main "$workrepo"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m init
  git -C "$workrepo" checkout -q -b ops/leftover

  CC_SESSION_NO_WORKTREE_HINT=1 \
    run "$CC_SESSION" -d "$workrepo" "$SESSION_NAME"
  assert_eq "$status" 0
  refute_contains "$output" "hint"
}

@test "hint is silent when --worktree is already in use" {
  upstream="${TEST_DIR}/upstream.git"
  workrepo="${TEST_DIR}/work"
  git init --bare -q "$upstream"
  git init -q -b main "$workrepo"
  git -C "$workrepo" remote add origin "$upstream"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m init
  git -C "$workrepo" push -q origin main
  git -C "$workrepo" checkout -q -b ops/leftover

  run "$CC_SESSION" -d -w ops/new "$workrepo" "$SESSION_NAME"
  assert_eq "$status" 0
  refute_contains "$output" "hint"
}

@test "hint is silent when PROJECT_DIR is not a git repo" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  refute_contains "$output" "hint"
}

@test "CC_SESSION_WORKTREE_BASE overrides the default 'origin/main' base ref" {
  upstream="${TEST_DIR}/upstream.git"
  workrepo="${TEST_DIR}/work"
  git init --bare -q "$upstream"
  git init -q -b main "$workrepo"
  git -C "$workrepo" remote add origin "$upstream"
  git -C "$workrepo" config user.email t@t
  git -C "$workrepo" config user.name t
  git -C "$workrepo" commit --allow-empty -q -m main-base
  git -C "$workrepo" push -q origin main
  # Build an alternate branch with a distinct commit, push it.
  git -C "$workrepo" checkout -q -b alt
  git -C "$workrepo" commit --allow-empty -q -m alt-base
  alt_sha="$(git -C "$workrepo" rev-parse HEAD)"
  git -C "$workrepo" push -q origin alt
  git -C "$workrepo" checkout -q main

  CC_SESSION_WORKTREE_BASE=origin/alt \
    run "$CC_SESSION" -d -w ops/from-alt "$workrepo" "$SESSION_NAME"
  assert_eq "$status" 0

  wt="${TEST_DIR}/work-wt/from-alt"
  wt_sha="$(git -C "$wt" rev-parse HEAD)"
  # New branch must point at origin/alt's tip, not main's.
  assert_eq "$wt_sha" "$alt_sha"
}

# --- parse_session_id (exercised via --teleport) ---------------------

@test "--teleport without an id exits 2" {
  run "$CC_SESSION" --teleport
  assert_eq "$status" 2
  assert_contains "$output" -- "--teleport requires a session id or URL"
}

@test "--teleport rejects whitespace" {
  run "$CC_SESSION" --teleport "has space"
  assert_eq "$status" 2
  assert_contains "$output" "invalid session id"
}

@test "--teleport rejects an empty URL suffix" {
  run "$CC_SESSION" --teleport "https://claude.ai/code/"
  assert_eq "$status" 2
  assert_contains "$output" "invalid session id"
}

@test "--teleport rejects punctuation" {
  run "$CC_SESSION" --teleport "session_!!!"
  assert_eq "$status" 2
  assert_contains "$output" "invalid session id"
}

@test "--teleport accepts a full URL and forwards canonical id to claude" {
  run "$CC_SESSION" -d -t "https://claude.ai/code/session_TEST123abc" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" -- "--teleport session_TEST123abc"
}

@test "--teleport accepts a bare session_xxx id" {
  run "$CC_SESSION" -d -t "session_TEST123abc" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" -- "--teleport session_TEST123abc"
}

@test "--teleport accepts a suffix-only id (prepends session_)" {
  run "$CC_SESSION" -d -t "TEST123abc" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" -- "--teleport session_TEST123abc"
}

@test "--teleport strips trailing slash, query, fragment" {
  for url in \
    "https://claude.ai/code/session_TEST123abc/" \
    "https://claude.ai/code/session_TEST123abc?foo=bar" \
    "https://claude.ai/code/session_TEST123abc#anchor"
  do
    sess="${SESSION_NAME}-${RANDOM}"
    run "$CC_SESSION" -d -t "$url" "$TEST_DIR" "$sess"
    assert_eq "$status" 0
    args="$(pane_args "$sess")"
    assert_contains "$args" -- "--teleport session_TEST123abc"
    tmux kill-session -t "$sess" 2>/dev/null || true
  done
}

# --- --resume <uuid> ------------------------------------------------

@test "--resume without a uuid exits 2" {
  run "$CC_SESSION" --resume
  assert_eq "$status" 2
  assert_contains "$output" -- "--resume requires a local session UUID"
}

@test "--resume rejects non-UUID strings" {
  run "$CC_SESSION" --resume "not-a-uuid"
  assert_eq "$status" 2
  assert_contains "$output" "invalid UUID for --resume"
}

@test "--resume rejects cloud session_xxx ids (different ID space)" {
  run "$CC_SESSION" --resume "session_01EXAMPLEab1234567890"
  assert_eq "$status" 2
  assert_contains "$output" "invalid UUID for --resume"
  assert_contains "$output" "use --teleport"
}

@test "--resume accepts canonical UUID and forwards to claude" {
  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" -- "--resume d8fd4550-d9cc-4ebe-9336-c20b7408afb1"
}

@test "--resume + --teleport mutually exclusive" {
  run "$CC_SESSION" --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" --teleport session_TEST
  assert_eq "$status" 2
  assert_contains "$output" "mutually exclusive"
}

@test "--resume + --adopt mutually exclusive" {
  run "$CC_SESSION" --adopt --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1"
  assert_eq "$status" 2
  assert_contains "$output" "mutually exclusive"
}

@test "--resume + --full exits 2 (--full is teleport-only)" {
  run "$CC_SESSION" --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" --full
  assert_eq "$status" 2
  assert_contains "$output" -- "--full requires --teleport"
}

@test "--resume launches /remote-control after settle and captures URL" {
  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # fake-claude --resume drops straight into stdin loop. cc-session's
  # post-launch sends /remote-control which fake-claude responds to
  # with the session_FAKE URL.
  wait_for_pane "$SESSION_NAME" "/remote-control is active" 30 \
    || { echo "fake-claude never received /remote-control after --resume"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]
  assert_contains "$(cat "$state_file")" "https://claude.ai/code/session_FAKE"
}

@test "--resume + --compact: /compact lands after URL capture" {
  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" --compact "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "fake: /compact received" 30 \
    || { echo "/compact never landed on --resume path"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
}

# Behaviour change (0.6.0 / issue #35 lever ②): a --resume/--teleport
# onto a SERVER-mode session is no longer a silent recycle — it would
# drop every session the server multiplexes (#30), so it is refused.
@test "--resume refuses to recycle a server-mode session (lever ②)" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(tmux show-options -t "$SESSION_NAME" -v '@cc-session-mode' 2>/dev/null || true)" "server"
  old_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"

  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to recycle"
  assert_contains "$output" "server-mode"
  # Server-mode session must be completely untouched.
  new_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"
  assert_eq "$old_pid" "$new_pid"
  tmux has-session -t "$SESSION_NAME"
}

@test "--resume refuses to kill an unmanaged tmux session" {
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "sleep 3600"
  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to kill"
}

# --- --full ----------------------------------------------------------

@test "--full without --teleport exits 2" {
  run "$CC_SESSION" --full
  assert_eq "$status" 2
  assert_contains "$output" -- "--full requires --teleport"
}

@test "--compact without --teleport exits 2 (server mode rejects slash commands)" {
  run "$CC_SESSION" --compact
  assert_eq "$status" 2
  assert_contains "$output" -- "--compact requires --teleport"
}

@test "--full + --compact rejected as self-defeating" {
  # Self-defeating: --full pays for full transcript load, --compact
  # immediately summarizes it. Strictly worse than just --teleport
  # (default summary mode).
  CC_SESSION_SKIP_FULL_CONFIRM=1 run "$CC_SESSION" -t session_TEST --full --compact
  assert_eq "$status" 2
  assert_contains "$output" "don't combine sensibly"
  assert_contains "$output" "drop --full"
  assert_contains "$output" "drop --compact"
}

@test "--full with 'no' prints warning, aborts, creates no session" {
  run bash -c "echo no | '$CC_SESSION' -d -t session_TEST --full '$TEST_DIR' '$SESSION_NAME'"
  assert_eq "$status" 1
  assert_contains "$output" "ENTIRE conversation"
  assert_contains "$output" "aborted"
  run tmux has-session -t "$SESSION_NAME"
  refute_contains "$status" 0  # has-session returns 1 when no session
}

@test "--full requires literal 'yes' (partial 'y' aborts)" {
  run bash -c "echo y | '$CC_SESSION' -d -t session_TEST --full '$TEST_DIR' '$SESSION_NAME'"
  assert_eq "$status" 1
  assert_contains "$output" "aborted"
}

@test "--full proceeds when user types exactly 'yes'" {
  run bash -c "echo yes | '$CC_SESSION' -d -t session_TEST --full '$TEST_DIR' '$SESSION_NAME'"
  assert_eq "$status" 0
  tmux has-session -t "$SESSION_NAME"
}

@test "CC_SESSION_SKIP_FULL_CONFIRM=1 bypasses the prompt" {
  CC_SESSION_SKIP_FULL_CONFIRM=1 run "$CC_SESSION" -d -t session_TEST --full "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  refute_contains "$output" 'Type "yes"'
  tmux has-session -t "$SESSION_NAME"
}

# --- @cc-session-managed marker -------------------------------------

@test "creating a session via cc-session sets @cc-session-managed=1" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(marker_value "$SESSION_NAME")" "1"
}

@test "--teleport refuses to kill an unmanaged tmux session" {
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "sleep 3600"
  assert_eq "$(marker_value "$SESSION_NAME")" ""

  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to kill"
  assert_contains "$output" "@cc-session-managed=1"
  tmux has-session -t "$SESSION_NAME"
}

@test "--teleport refuses to recycle a server-mode session (lever ②, #30)" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(tmux show-options -t "$SESSION_NAME" -v '@cc-session-mode' 2>/dev/null || true)" "server"
  old_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"

  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to recycle"
  assert_contains "$output" "server-mode"
  assert_contains "$output" "issue #30"
  # The bastion-class footgun: server must survive untouched.
  new_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"
  assert_eq "$old_pid" "$new_pid"
  assert_eq "$(marker_value "$SESSION_NAME")" "1"
}

# --- Argument forwarding (default launch uses `remote-control`) ----

@test "default launch invokes the remote-control subcommand" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" "remote-control"
  refute_contains "$args" -- "--teleport"
}

# --- Post-launch URL capture (background subshell) ------------------

@test "background flow captures the server-mode URL on default launch" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Server mode: the URL is printed automatically on startup, no
  # /remote-control keystroke is sent.
  wait_for_pane "$SESSION_NAME" "https://claude.ai/code?environment=env_FAKE" 30 \
    || { echo "Pane never received the expected server URL:"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
  # State file written at $TMPDIR/cc-session/<NAME>.url
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]
  url="$(cat "$state_file")"
  assert_contains "$url" "https://claude.ai/code?environment=env_FAKE"
}

@test "default launch does NOT send the /remote-control slash command" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Give the (now-absent) keystroke flow more than enough time to fire.
  sleep 3
  pane="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  # fake-claude's remote-control branch echoes any received stdin as
  # "server stdin: <line>". If cc-session erroneously sends a slash
  # command into a server-mode pane, it would surface here.
  refute_contains "$pane" "server stdin: /remote-control"
  refute_contains "$pane" "/remote-control is active"
}

@test "/compact fires AFTER URL capture, not on a fixed delay" {
  run "$CC_SESSION" -d -t session_TEST --compact "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # First the URL must be captured (proving claude reached idle).
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]
  # THEN /compact lands. fake-claude echoes "fake: /compact received"
  # when it reads /compact on stdin.
  wait_for_pane "$SESSION_NAME" "fake: /compact received" 30 \
    || { echo "fake-claude never received /compact"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
}

@test "background flow sends Enter (summary) when --teleport given" {
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "fake: resume key summary (Enter) received" 30 \
    || { echo "fake-claude never received summary Enter"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
}

@test "background flow sends Down+Enter (full) when --teleport --full" {
  CC_SESSION_SKIP_FULL_CONFIRM=1 run "$CC_SESSION" -d -t session_TEST --full "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "fake: resume key full (Down) received" 30 \
    || { echo "fake-claude never received Down arrow for full"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
}

@test "--teleport --full sets DISABLE_AUTO_COMPACT=1 in claude env" {
  CC_SESSION_SKIP_FULL_CONFIRM=1 run "$CC_SESSION" -d -t session_TEST --full "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "fake claude env: DISABLE_AUTO_COMPACT=1" 30 \
    || { echo "DISABLE_AUTO_COMPACT=1 not seen in fake-claude output"; \
         tmux capture-pane -t "$SESSION_NAME" -p; \
         return 1; }
}

@test "--teleport without --full does NOT set DISABLE_AUTO_COMPACT" {
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  sleep 2
  pane="$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null || true)"
  refute_contains "$pane" "DISABLE_AUTO_COMPACT"
}

# --- --adopt flag ----------------------------------------------------

@test "--adopt + --teleport mutually exclusive" {
  run "$CC_SESSION" --adopt -t session_TEST
  assert_eq "$status" 2
  assert_contains "$output" "mutually exclusive"
}

@test "--adopt incompatible with --detach / --compact / --full" {
  run "$CC_SESSION" --adopt -d
  assert_eq "$status" 2
  assert_contains "$output" "incompatible"
}

@test "--adopt fails on nonexistent tmux session" {
  run "$CC_SESSION" --adopt "definitely-not-here-$$-$BATS_TEST_NUMBER"
  assert_eq "$status" 1
  assert_contains "$output" "does not exist"
}

@test "--adopt refuses an unmanaged tmux session" {
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "sleep 3600"
  run "$CC_SESSION" --adopt "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to adopt unmanaged"
  assert_contains "$output" "@cc-session-managed marker"
}

@test "--adopt enables RC on managed session and prints URL" {
  # Pre-create a managed session with fake-claude (it reads stdin so
  # our /remote-control keystroke gets a response).
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "$FAKE_CLAUDE"
  tmux set-option -t "$SESSION_NAME" -q '@cc-session-managed' '1'
  sleep 0.5  # let fake-claude reach its read loop

  run "$CC_SESSION" --adopt "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "Remote Control on '$SESSION_NAME'"
  assert_contains "$output" "https://claude.ai/code/session_FAKE"

  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  [ -f "$state_file" ]
  assert_contains "$(cat "$state_file")" "https://claude.ai/code/session_FAKE"
}

@test "--adopt is idempotent: second call returns same URL without re-sending" {
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "$FAKE_CLAUDE"
  tmux set-option -t "$SESSION_NAME" -q '@cc-session-managed' '1'
  sleep 0.5

  run "$CC_SESSION" --adopt "$SESSION_NAME"
  assert_eq "$status" 0
  url1="$(printf '%s\n' "$output" | grep -oE 'https://claude\.ai/code/session_FAKE[0-9]+')"

  run "$CC_SESSION" --adopt "$SESSION_NAME"
  assert_eq "$status" 0
  url2="$(printf '%s\n' "$output" | grep -oE 'https://claude\.ai/code/session_FAKE[0-9]+')"

  assert_eq "$url1" "$url2"
}

@test "--adopt rejects 2 positionals (tmux-name mode is single-positional)" {
  run "$CC_SESSION" --adopt some-dir some-session
  assert_eq "$status" 2
  assert_contains "$output" "takes at most one positional"
}

@test "--adopt with bare ULID-shaped arg auto-delegates to --teleport flow" {
  # 24-char alphanumeric — cloud session id shape (no hyphens or
  # underscores). cc-session should switch to --teleport mode and
  # run claude --teleport <canonical-id>.
  run "$CC_SESSION" -d --adopt 01ABCDEFGHIJklmnopqrstuv "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "switching to --teleport mode"
  args="$(pane_args "$SESSION_NAME")"
  # parse_session_id prepends session_ to bare suffix
  assert_contains "$args" -- "--teleport session_01ABCDEFGHIJklmnopqrstuv"
}

@test "--adopt with session_-prefixed arg auto-delegates to --teleport flow" {
  run "$CC_SESSION" -d --adopt session_01TESTabcdef1234567890 "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "switching to --teleport mode"
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" -- "--teleport session_01TESTabcdef1234567890"
}

@test "--adopt with claude.ai URL auto-delegates and parses URL" {
  run "$CC_SESSION" -d --adopt "https://claude.ai/code/session_01URLabc1234567890ABCD" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "switching to --teleport mode"
  args="$(pane_args "$SESSION_NAME")"
  assert_contains "$args" -- "--teleport session_01URLabc1234567890ABCD"
}

@test "--adopt accepts a regular tmux name with hyphens (not flagged as cloud ID)" {
  # Even though >20 chars, hyphens disqualify the ULID heuristic.
  long_name="my-very-long-tmux-session-name"
  run "$CC_SESSION" --adopt "$long_name"
  # Will fail with "does not exist" (no such tmux session) — which is
  # the right error class. The point: not flagged as cloud ID.
  assert_eq "$status" 1
  assert_contains "$output" "does not exist"
  refute_contains "$output" "cloud session"
}

@test "--adopt tmux-name mode rejects --detach (incompatible)" {
  # Pre-create managed tmux so adopt would otherwise succeed.
  tmux new-session -d -s "$SESSION_NAME" -c "$TEST_DIR" "$FAKE_CLAUDE"
  tmux set-option -t "$SESSION_NAME" -q '@cc-session-managed' '1'
  sleep 0.3
  run "$CC_SESSION" --adopt -d "$SESSION_NAME"
  assert_eq "$status" 2
  assert_contains "$output" "incompatible"
}

# --- Error paths -----------------------------------------------------

@test "missing PROJECT_DIR exits 1 with clear message" {
  run "$CC_SESSION" "/tmp/cc-session-no-such-dir-$$"
  assert_eq "$status" 1
  assert_contains "$output" "directory not found"
}

@test "-d on an already-running session is a no-op (does not respawn)" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "started"
  first_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"

  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "already running"
  second_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"
  assert_eq "$first_pid" "$second_pid"
}

# --- --update --------------------------------------------------------

# Build a throwaway git repo at $TEST_DIR/$1 with N empty commits.
mk_repo() {
  local path="$TEST_DIR/$1"; shift
  local n="${1:-1}"
  git init -q -b main "$path"
  git -C "$path" config user.email "t@t"
  git -C "$path" config user.name "t"
  local i
  for i in $(seq 1 "$n"); do
    git -C "$path" commit --allow-empty -q -m "c$i"
  done
}

@test "--update without git repo errors with install hint" {
  CC_SESSION_UPDATE_REPO="$TEST_DIR" run "$CC_SESSION" --update
  assert_eq "$status" 1
  assert_contains "$output" "requires a git checkout"
  assert_contains "$output" "git clone"
}

@test "--update --check on synced repo reports up to date" {
  mk_repo synced 1
  CC_SESSION_UPDATE_REPO="$TEST_DIR/synced" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/synced" \
    run "$CC_SESSION" --update --check
  assert_eq "$status" 0
  assert_contains "$output" "up to date"
}

@test "--update --check on behind repo lists upstream commits" {
  mk_repo upstream 1
  # Clone the upstream into 'local' before adding c2, so 'local' is one
  # commit behind once upstream gets its second commit.
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 new upstream"

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    run "$CC_SESSION" --update --check
  assert_eq "$status" 0
  assert_contains "$output" "1 upstream commit"
}

@test "--update on behind repo refuses without tty + UPDATE_YES" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 new upstream"

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    run "$CC_SESSION" --update
  assert_eq "$status" 1
  assert_contains "$output" "stdin is not a tty"
}

@test "--update with UPDATE_YES fast-forwards a behind repo" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 new upstream"

  local before_sha after_sha upstream_sha
  before_sha=$(git -C "$TEST_DIR/local" rev-parse HEAD)
  upstream_sha=$(git -C "$TEST_DIR/upstream" rev-parse HEAD)

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    CC_SESSION_UPDATE_YES=1 \
    run "$CC_SESSION" --update
  assert_eq "$status" 0
  after_sha=$(git -C "$TEST_DIR/local" rev-parse HEAD)
  assert_eq "$after_sha" "$upstream_sha"
  [[ "$after_sha" != "$before_sha" ]]
}

@test "--update refuses when local has diverged commits" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  # Upstream advances by one commit; local independently advances by
  # one commit. Both branches are now 1-ahead-of-the-other.
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2-upstream"
  git -C "$TEST_DIR/local" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2-local"

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    CC_SESSION_UPDATE_YES=1 \
    run "$CC_SESSION" --update
  assert_eq "$status" 1
  assert_contains "$output" "refusing to update"
  assert_contains "$output" "not in upstream"
}

@test "--update refuses when working tree is dirty" {
  mk_repo upstream 1
  # Commit a tracked file in upstream so the clone has something to dirty.
  echo "v1" > "$TEST_DIR/upstream/file"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t add file
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit -q -m "add tracked file"
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  # Upstream advances; local stays behind so the dirty check is reached.
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c3 new upstream"
  # Modify the tracked file in local without staging/committing.
  echo "v2-dirty" > "$TEST_DIR/local/file"

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    CC_SESSION_UPDATE_YES=1 \
    run "$CC_SESSION" --update
  assert_eq "$status" 1
  assert_contains "$output" "uncommitted changes"
}

@test "--update on local-ahead repo reports nothing to pull" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/local" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 local-only"

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    run "$CC_SESSION" --update
  assert_eq "$status" 0
  assert_contains "$output" "ahead of upstream"
}

@test "--update --check on non-main branch warns about feature-branch ff" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 new upstream"
  git -C "$TEST_DIR/local" checkout -q -b feat/something

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    run "$CC_SESSION" --update --check
  assert_eq "$status" 0
  assert_contains "$output" "WARNING"
  assert_contains "$output" "feat/something"
}

@test "--update refuses scripted ff on non-main branch without ALLOW_NONMAIN" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 new upstream"
  git -C "$TEST_DIR/local" checkout -q -b feat/something

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    CC_SESSION_UPDATE_YES=1 \
    run "$CC_SESSION" --update
  assert_eq "$status" 1
  assert_contains "$output" "refusing to update"
  assert_contains "$output" "non-main branch"
}

@test "--update with ALLOW_NONMAIN fast-forwards a feature branch" {
  mk_repo upstream 1
  git clone -q "$TEST_DIR/upstream" "$TEST_DIR/local"
  git -C "$TEST_DIR/upstream" -c user.email=t@t -c user.name=t \
    commit --allow-empty -q -m "c2 new upstream"
  git -C "$TEST_DIR/local" checkout -q -b feat/something

  local upstream_sha
  upstream_sha=$(git -C "$TEST_DIR/upstream" rev-parse HEAD)

  CC_SESSION_UPDATE_REPO="$TEST_DIR/local" \
    CC_SESSION_UPDATE_URL="$TEST_DIR/upstream" \
    CC_SESSION_UPDATE_YES=1 \
    CC_SESSION_UPDATE_ALLOW_NONMAIN=1 \
    run "$CC_SESSION" --update
  assert_eq "$status" 0
  local after_sha
  after_sha=$(git -C "$TEST_DIR/local" rev-parse HEAD)
  assert_eq "$after_sha" "$upstream_sha"
}

# ====================================================================
# @cc-session-mode state machine (issue #35 levers ①②④⑤⑥⑦)
# ====================================================================

# --- mode markers ---------------------------------------------------

@test "default launch stamps @cc-session-mode=server" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(mode_value "$SESSION_NAME")" "server"
  assert_eq "$(marker_value "$SESSION_NAME")" "1"
}

@test "--teleport stamps @cc-session-mode=teleport" {
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(mode_value "$SESSION_NAME")" "teleport"
}

@test "--resume stamps @cc-session-mode=teleport" {
  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(mode_value "$SESSION_NAME")" "teleport"
}

# --- ① fail-loud safe naming ----------------------------------------

@test "① --teleport with no explicit name auto-allocates claude-tp-<id8>-<hex>" {
  run "$CC_SESSION" -d -t session_DEADBEEF12345 "$TEST_DIR"
  assert_eq "$status" 0
  assert_contains "$output" "teleport tmux session: claude-tp-DEADBEEF-"
  auto="$(autoname_for DEADBEEF)"
  [ -n "$auto" ] || { echo "no claude-tp-DEADBEEF-<hex> session found"; \
                       tmux list-sessions; return 1; }
  assert_eq "$(mode_value "$auto")" "teleport"
  # The bare 'claude' name (the #30 footgun) must NOT have been used.
  # NB: `tmux has-session -t claude` prefix-matches claude-tp-*, so
  # assert on an exact session-name listing instead.
  if tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -qx 'claude'; then
    echo "footgun: a bare 'claude' tmux session was created"; \
      tmux list-sessions; return 1
  fi
}

@test "① --resume with no explicit name auto-allocates from the uuid" {
  run "$CC_SESSION" -d --resume "d8fd4550-d9cc-4ebe-9336-c20b7408afb1" "$TEST_DIR"
  assert_eq "$status" 0
  auto="$(autoname_for d8fd4550)"
  [ -n "$auto" ] || { echo "no claude-tp-d8fd4550-<hex> session"; \
                       tmux list-sessions; return 1; }
}

@test "① name collision is a HARD ERROR, never a recycle/kill (the invariant)" {
  # Pre-create the exact session the override will try to allocate.
  tmux new-session -d -s "claude-tp-COLLIDE0-aaaaaa" -c "$TEST_DIR" "sleep 300"
  victim_pid="$(tmux list-panes -t "claude-tp-COLLIDE0-aaaaaa" -F '#{pane_pid}' | head -1)"

  CC_SESSION_RAND6HEX_OVERRIDE=aaaaaa \
    run "$CC_SESSION" -d -t session_COLLIDE012345 "$TEST_DIR"
  assert_eq "$status" 1
  assert_contains "$output" "could not allocate a collision-free teleport tmux name"
  assert_contains "$output" "NEVER falls back to recycling"

  # Invariant: the colliding session was NOT killed/recycled.
  run tmux has-session -t "claude-tp-COLLIDE0-aaaaaa"
  assert_eq "$status" 0
  still_pid="$(tmux list-panes -t "claude-tp-COLLIDE0-aaaaaa" -F '#{pane_pid}' | head -1)"
  assert_eq "$victim_pid" "$still_pid"
}

# --- ⑥ single-session gate ------------------------------------------

@test "⑥ re-teleport onto a teleport-mode session is refused (--kill first)" {
  run "$CC_SESSION" -d -t session_GATE1 "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(mode_value "$SESSION_NAME")" "teleport"
  first_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"

  run "$CC_SESSION" -d -t session_GATE2 "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to reuse"
  assert_contains "$output" "single-use"
  # Original teleport session untouched.
  same_pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"
  assert_eq "$first_pid" "$same_pid"
}

@test "⑥ --adopt onto a teleport-mode session is refused" {
  run "$CC_SESSION" -d -t session_ADOPT1 "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(mode_value "$SESSION_NAME")" "teleport"

  run "$CC_SESSION" --adopt "$SESSION_NAME"
  assert_eq "$status" 1
  assert_contains "$output" "refusing to adopt"
  assert_contains "$output" "single-use"
  tmux has-session -t "$SESSION_NAME"
}

# --- ⑤ revive-audit -------------------------------------------------

@test "⑤ --teleport writes a launch audit record then a url-captured one" {
  audit="${TEST_DIR}/audit.jsonl"
  run "$CC_SESSION" -d -t session_AUDITxyz "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  [ -f "$audit" ] || { echo "no audit file at $audit"; return 1; }
  grep -q '"event":"launch"' "$audit" \
    || { echo "no launch record:"; cat "$audit"; return 1; }
  assert_contains "$(cat "$audit")" '"requested_id":"session_AUDITxyz"'
  assert_contains "$(cat "$audit")" "\"tmux\":\"$SESSION_NAME\""

  # url-captured is appended by the async post-launch subshell.
  for _ in $(seq 1 40); do
    grep -q '"event":"url-captured"' "$audit" && break
    sleep 0.5
  done
  grep -q '"event":"url-captured"' "$audit" \
    || { echo "no url-captured record:"; cat "$audit"; return 1; }
  assert_contains "$(cat "$audit")" "session_FAKE"
}

@test "⑤ audit is best-effort: an unwritable audit path does not fail launch" {
  CC_SESSION_AUDIT_FILE="/dev/null/nope/audit.jsonl" \
    run "$CC_SESSION" -d -t session_BESTEFFORT "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  tmux has-session -t "$SESSION_NAME"
}

# --- ⑦ [T] display-title prefix -------------------------------------

@test "⑦ teleport launch passes CLAUDE_REMOTE_CONTROL_SESSION_NAME_PREFIX='[T] '" {
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "fake claude rc-prefix:[[T] ]" 30 \
    || { echo "rc-prefix env never reached fake-claude"; \
         tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
}

@test "⑦ CC_SESSION_TELEPORT_TITLE_PREFIX overrides the prefix" {
  CC_SESSION_TELEPORT_TITLE_PREFIX='QA ' \
    run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "fake claude rc-prefix:[QA ]" 30 \
    || { echo "custom rc-prefix never reached fake-claude"; \
         tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
}

@test "⑦ empty CC_SESSION_TELEPORT_TITLE_PREFIX disables the prefix wrapper" {
  CC_SESSION_TELEPORT_TITLE_PREFIX='' \
    run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # fake-claude must still come up (resume key flow), but with no prefix.
  wait_for_pane "$SESSION_NAME" "fake: resume key summary (Enter) received" 30 \
    || { echo "teleport flow broke with empty prefix"; \
         tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  pane="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  refute_contains "$pane" "rc-prefix"
}

@test "⑦ server-mode launch never gets the teleport prefix" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "https://claude.ai/code?environment=env_FAKE" 30 \
    || { echo "server URL never appeared"; \
         tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  pane="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  refute_contains "$pane" "rc-prefix"
}

# --- ④ auto-reaper --------------------------------------------------

@test "④ teleport session is reaped once its claude exits (dead pane)" {
  export CC_SESSION_NO_REAP=0
  export CC_SESSION_REAP_POLL=1
  export CC_SESSION_REAP_GRACE=1
  audit="${TEST_DIR}/audit.jsonl"

  run "$CC_SESSION" -d -t session_REAP "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Wait until the URL is captured (proves the post-launch subshell has
  # reached the reaper loop).
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in $(seq 1 40); do [ -f "$state_file" ] && break; sleep 0.5; done
  [ -f "$state_file" ]

  # Kill claude; remain-on-exit holds a dead pane the reaper must sweep.
  pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"
  kill "$pid" 2>/dev/null || true

  for _ in $(seq 1 60); do
    tmux has-session -t "$SESSION_NAME" 2>/dev/null || break
    sleep 0.5
  done
  run tmux has-session -t "$SESSION_NAME"
  refute_contains "$status" 0   # session was reaped

  grep -q '"event":"reap"' "$audit" \
    || { echo "no reap audit record:"; cat "$audit" 2>/dev/null; return 1; }
}

@test "④ CC_SESSION_NO_REAP=1 preserves the dead teleport pane" {
  # setup() exports CC_SESSION_NO_REAP=1 already — this is the default.
  run "$CC_SESSION" -d -t session_NOREAP "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in $(seq 1 40); do [ -f "$state_file" ] && break; sleep 0.5; done

  pid="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_pid}' | head -1)"
  kill "$pid" 2>/dev/null || true
  sleep 4   # longer than a default poll+grace would need

  # Reaper disabled ⇒ tmux session persists with a dead pane.
  tmux has-session -t "$SESSION_NAME"
  pd="$(tmux list-panes -s -t "$SESSION_NAME" -F '#{pane_dead}' | head -1)"
  assert_eq "$pd" "1"
}

@test "④ server-mode is NEVER reaped even with the reaper enabled" {
  export CC_SESSION_NO_REAP=0
  export CC_SESSION_REAP_POLL=1
  export CC_SESSION_REAP_GRACE=1
  CC_FAKE_CLAUDE_CRASH=1 CC_SESSION_RC_URL_TIMEOUT=2 \
    CC_SESSION_SV_MAX_FAILS=1 CC_SESSION_SV_BACKOFF_BASE=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_eq "$(mode_value "$SESSION_NAME")" "server"

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    pd="$(tmux list-panes -s -t "$SESSION_NAME" -F '#{pane_dead}' 2>/dev/null | head -1 || true)"
    [ "$pd" = "1" ] && break
    sleep 0.3
  done
  assert_eq "$pd" "1"
  sleep 5   # well past poll+grace; a teleport session would be gone

  # Scope guard: server-mode dead pane must persist for debuggability.
  tmux has-session -t "$SESSION_NAME"
}

# ====================================================================
# tmux exact-match target regression (servarica e2e run #1 finding):
# tmux resolves `-t name` by exact→PREFIX→fnmatch. With a server-mode
# `claude` plus an auto `claude-tp-<id8>-<hex>`, once exact `claude`
# is gone a bare `-t claude` silently prefix-matched the teleport —
# ②/--kill/--status/reaper acted on the WRONG session. cc-session now
# uses `-t "=NAME"` everywhere it must hit one exact session.
# ====================================================================

@test "exact-match: --kill NAME never prefix-kills a NAME-prefixed neighbour" {
  # Only '<NAME>LONG' exists; there is NO exact '<NAME>' session.
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "${SESSION_NAME}LONG"
  assert_eq "$status" 0
  has_exact "${SESSION_NAME}LONG"

  run "$CC_SESSION" --kill "$SESSION_NAME"
  refute_contains "$status" 0          # no exact match -> nothing killed
  # The prefix neighbour must be untouched (pre-fix it got killed).
  has_exact "${SESSION_NAME}LONG"
}

@test "exact-match: --teleport NAME with only NAME-prefixed present doesn't mis-resolve" {
  # A teleport-mode '<NAME>LONG' exists; NO exact '<NAME>'.
  run "$CC_SESSION" -d -t session_AAA "$TEST_DIR" "${SESSION_NAME}LONG"
  assert_eq "$status" 0
  assert_eq "$(mode_value "${SESSION_NAME}LONG")" "teleport"

  # cc-session -t ... NAME must NOT prefix-resolve to '<NAME>LONG' and
  # emit a bogus ⑥/② refusal (the exact servarica Phase-4 symptom);
  # it should create the genuine exact '<NAME>'.
  run "$CC_SESSION" -d -t session_BBB "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  refute_contains "$output" "refusing to reuse"
  refute_contains "$output" "refusing to recycle"
  has_exact "$SESSION_NAME"
  assert_eq "$(mode_value "$SESSION_NAME")" "teleport"
  has_exact "${SESSION_NAME}LONG"   # neighbour untouched
}

@test "exact-match: --status NAME ignores a NAME-prefixed neighbour" {
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "${SESSION_NAME}LONG"
  assert_eq "$status" 0

  run "$CC_SESSION" --status "$SESSION_NAME"
  assert_eq "$status" 1                 # exact NAME absent -> not alive
  assert_contains "$output" "session: $SESSION_NAME"
  assert_contains "$output" "alive: no"
  refute_contains "$output" "${SESSION_NAME}LONG"
}

# ====================================================================
# v0.7 P1: bash migration, supervisor, naming, session_id addressing
# ====================================================================

# --- C1: bash migration ----------------------------------------------

@test "C1: shebang is bash, not zsh" {
  head -1 "$CC_SESSION" | grep -q '#!/usr/bin/env bash'
}

@test "C1: no zsh-only constructs remain in the script" {
  # ${0:A}, ${var:h}, ${(j:)}, ${(@q)} are zsh-specific.
  # grep returns 0 if found — we want NOT found, so negate.
  ! grep -E '\$\{0:A\}|\$\{[a-zA-Z_]+:h\}|\$\{\(j:|\$\{\(@q\)' "$CC_SESSION"
}

@test "C1: SCRIPT_PATH uses realpath (not zsh \${0:A})" {
  grep -q 'SCRIPT_PATH=.*realpath' "$CC_SESSION"
}

@test "C1: printf %q quoting round-trips spaces and brackets in teleport launch" {
  # Teleport with a prefix containing spaces and brackets must survive
  # the printf %q → bash -lc round-trip.
  CC_SESSION_TELEPORT_TITLE_PREFIX="[Test Prefix] " \
    run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "rc-prefix:" 10 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p)"
  assert_contains "$buf" "rc-prefix:[[Test Prefix] ]"
}

# --- C2: supervisor loop (server-mode) --------------------------------

@test "C2: server-mode pane shows [cc-sv] supervisor log prefix" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "[cc-sv]" 10 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p)"
  assert_contains "$buf" "[cc-sv] starting claude"
}

@test "C2: teleport-mode does NOT run supervisor (no [cc-sv] prefix)" {
  run "$CC_SESSION" -d -t session_TEST "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  sleep 1
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p 2>/dev/null)"
  refute_contains "$buf" "[cc-sv]"
}

@test "C2: circuit breaker stops after SV_MAX_FAILS consecutive crashes" {
  CC_FAKE_CLAUDE_CRASH=1 \
    CC_SESSION_SV_MAX_FAILS=2 \
    CC_SESSION_SV_BACKOFF_BASE=1 \
    CC_SESSION_RC_URL_TIMEOUT=2 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Wait for circuit breaker message (2 crashes × ~0.5s each + 1s backoff)
  wait_for_pane "$SESSION_NAME" "CIRCUIT BREAKER" 15 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  assert_contains "$buf" "CIRCUIT BREAKER: 2 consecutive failures"
  assert_contains "$buf" "supervisor stopped"
}

@test "C2: pre-respawn auth probe runs before backoff" {
  # Use a stub that crashes once, then the supervisor probes auth and
  # respawns. We just need to see the auth probe message.
  CC_FAKE_CLAUDE_CRASH=1 \
    CC_SESSION_SV_MAX_FAILS=3 \
    CC_SESSION_SV_BACKOFF_BASE=1 \
    CC_SESSION_RC_URL_TIMEOUT=2 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "auth probe" 15 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  assert_contains "$buf" "[cc-sv] pre-respawn auth probe..."
  assert_contains "$buf" "[cc-sv] auth probe OK"
}

@test "C2: auth probe failure is logged" {
  CC_FAKE_CLAUDE_CRASH=1 \
    CC_FAKE_AUTH_FAIL=1 \
    CC_SESSION_SV_MAX_FAILS=2 \
    CC_SESSION_SV_BACKOFF_BASE=1 \
    CC_SESSION_RC_URL_TIMEOUT=2 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "auth probe FAILED" 15 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  assert_contains "$buf" "[cc-sv] auth probe FAILED"
}

@test "C2: SV_BACKOFF_MAX caps the delay" {
  CC_FAKE_CLAUDE_CRASH=1 \
    CC_SESSION_SV_MAX_FAILS=4 \
    CC_SESSION_SV_BACKOFF_BASE=10 \
    CC_SESSION_SV_BACKOFF_MAX=15 \
    CC_SESSION_RC_URL_TIMEOUT=2 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # After attempt 2: delay would be 10*2=20, capped to 15.
  wait_for_pane "$SESSION_NAME" "backoff 15s" 30 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  assert_contains "$buf" "[cc-sv] backoff 15s..."
}

# --- C3: session naming -----------------------------------------------

@test "C3: default session name is cc-YYYYMMDD-VERSION" {
  # fake-claude --version returns CC_FAKE_CLAUDE_VERSION (default 2.1.185).
  run "$CC_SESSION" -d "$TEST_DIR"
  assert_eq "$status" 0
  today="$(date +%Y%m%d)"
  expected="cc-${today}-2-1-185"
  # The output should mention the session name.
  assert_contains "$output" "$expected"
  # Clean up the auto-named session.
  tmux kill-session -t "$expected" 2>/dev/null || true
}

@test "C3: explicit session name overrides the default" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "$SESSION_NAME"
}

@test "C3: CC_FAKE_CLAUDE_VERSION controls the version in the default name" {
  CC_FAKE_CLAUDE_VERSION="3.0.0" \
    run "$CC_SESSION" -d "$TEST_DIR"
  assert_eq "$status" 0
  today="$(date +%Y%m%d)"
  expected="cc-${today}-3-0-0"
  assert_contains "$output" "$expected"
  tmux kill-session -t "$expected" 2>/dev/null || true
}

# --- C4: session_id ($NNN) addressing ----------------------------------

@test "C4: session id is captured and used for tmux operations" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # The session should have a numeric $NNN id assigned by tmux.
  sid="$(tmux list-sessions -F '#{session_name} #{session_id}' 2>/dev/null \
    | awk -v n="$SESSION_NAME" '$1 == n {print $2}')"
  [ -n "$sid" ]
  # Verify the id starts with $ (tmux convention).
  assert_contains "$sid" '$'
}

@test "C4: post-launch background flow works via session_id (URL captured)" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "https://claude.ai/code?environment=env_FAKE" 30 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  state_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.url"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state_file" ] && break
    sleep 0.5
  done
  [ -f "$state_file" ]
  url="$(cat "$state_file")"
  assert_contains "$url" "https://claude.ai/code?environment=env_FAKE"
}

# ====================================================================
# v0.7 P2: IPC, metrics, health watchdog
# ====================================================================

# --- C7: health watchdog -----------------------------------------------

@test "C7: supervisor writes .health file" {
  CC_SESSION_SV_WATCHDOG_INTERVAL=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  health_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.health"
  for _ in $(seq 1 20); do
    [ -f "$health_file" ] && break
    sleep 0.5
  done
  [ -f "$health_file" ]
  hc="$(cat "$health_file")"
  assert_contains "$hc" "status:"
  assert_contains "$hc" "auth:"
}

@test "C7: supervisor writes .prom file with auth_healthy" {
  CC_SESSION_SV_WATCHDOG_INTERVAL=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  prom_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.prom"
  for _ in $(seq 1 20); do
    [ -f "$prom_file" ] && break
    sleep 0.5
  done
  [ -f "$prom_file" ]
  pc="$(cat "$prom_file")"
  assert_contains "$pc" "auth_healthy="
  assert_contains "$pc" "respawn_total="
}

# --- C6: metrics output -----------------------------------------------

@test "C6: --metrics outputs prometheus textformat for a live session" {
  CC_SESSION_SV_WATCHDOG_INTERVAL=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Wait for prom file to exist.
  prom_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.prom"
  for _ in $(seq 1 20); do
    [ -f "$prom_file" ] && break
    sleep 0.5
  done
  run "$CC_SESSION" --metrics "$SESSION_NAME"
  assert_eq "$status" 0
  assert_contains "$output" "cc_session_up"
  assert_contains "$output" "cc_session_auth_healthy"
  assert_contains "$output" "cc_session_uptime_seconds"
  assert_contains "$output" "cc_session_respawn_total"
  assert_contains "$output" "# TYPE cc_session_up gauge"
}

@test "C6: --metrics with no arg lists all managed sessions" {
  CC_SESSION_SV_WATCHDOG_INTERVAL=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  prom_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.prom"
  for _ in $(seq 1 20); do
    [ -f "$prom_file" ] && break
    sleep 0.5
  done
  run "$CC_SESSION" --metrics
  assert_eq "$status" 0
  assert_contains "$output" "session=\"$SESSION_NAME\""
}

# --- C5: IPC (--ctl) ---------------------------------------------------

@test "C5: supervisor creates .ctl named pipe" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  ctl_pipe="${BATS_TMPDIR}/cc-session/$SESSION_NAME.ctl"
  for _ in $(seq 1 20); do
    [ -p "$ctl_pipe" ] && break
    sleep 0.5
  done
  [ -p "$ctl_pipe" ]
}

@test "C5: --ctl health reads the health file" {
  CC_SESSION_SV_WATCHDOG_INTERVAL=1 \
    run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  health_file="${BATS_TMPDIR}/cc-session/$SESSION_NAME.health"
  for _ in $(seq 1 20); do
    [ -f "$health_file" ] && break
    sleep 0.5
  done
  run "$CC_SESSION" --ctl "$SESSION_NAME" health
  assert_eq "$status" 0
  assert_contains "$output" "status:"
  assert_contains "$output" "auth:"
}

@test "C5: --ctl respawn kills current claude, supervisor restarts" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  # Wait for supervisor to be running.
  wait_for_pane "$SESSION_NAME" "[cc-sv] starting claude" 10 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  ctl_pipe="${BATS_TMPDIR}/cc-session/$SESSION_NAME.ctl"
  for _ in $(seq 1 10); do
    [ -p "$ctl_pipe" ] && break
    sleep 0.5
  done
  run "$CC_SESSION" --ctl "$SESSION_NAME" respawn
  assert_eq "$status" 0
  assert_contains "$output" "respawn command sent"
  # Wait for the respawn to show up in the pane.
  sleep 2
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  assert_contains "$buf" "[cc-sv] IPC: respawn requested"
}

@test "C5: --ctl stop gracefully stops the supervisor" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  wait_for_pane "$SESSION_NAME" "[cc-sv] starting claude" 10 \
    || { tmux capture-pane -t "$SESSION_NAME" -p; return 1; }
  ctl_pipe="${BATS_TMPDIR}/cc-session/$SESSION_NAME.ctl"
  for _ in $(seq 1 10); do
    [ -p "$ctl_pipe" ] && break
    sleep 0.5
  done
  run "$CC_SESSION" --ctl "$SESSION_NAME" stop
  assert_eq "$status" 0
  # Wait for supervisor to process stop and exit.
  wait_for_pane "$SESSION_NAME" "stop flag set" 15 \
    || wait_for_pane "$SESSION_NAME" "supervisor stopped" 10 \
    || true
  buf="$(tmux capture-pane -t "$SESSION_NAME" -p -S -200)"
  assert_contains "$buf" "[cc-sv] IPC: stop requested"
}

@test "C5: --ctl with unknown command exits 2" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  run "$CC_SESSION" --ctl "$SESSION_NAME" bogus
  assert_eq "$status" 2
  assert_contains "$output" "unknown --ctl command"
}

@test "C5: --ctl without session name exits 2" {
  run "$CC_SESSION" --ctl
  assert_eq "$status" 2
}

@test "C5: --kill cleans up all state files including .ctl pipe" {
  run "$CC_SESSION" -d "$TEST_DIR" "$SESSION_NAME"
  assert_eq "$status" 0
  ctl_pipe="${BATS_TMPDIR}/cc-session/$SESSION_NAME.ctl"
  for _ in $(seq 1 10); do
    [ -p "$ctl_pipe" ] && break
    sleep 0.5
  done
  run "$CC_SESSION" --kill "$SESSION_NAME"
  assert_eq "$status" 0
  # Brief settle for any async cleanup from supervisor EXIT trap.
  sleep 0.5
  [ ! -p "$ctl_pipe" ]
  [ ! -f "${BATS_TMPDIR}/cc-session/$SESSION_NAME.url" ]
  [ ! -f "${BATS_TMPDIR}/cc-session/$SESSION_NAME.health" ]
  [ ! -f "${BATS_TMPDIR}/cc-session/$SESSION_NAME.prom" ]
}
