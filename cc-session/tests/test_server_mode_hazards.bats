#!/usr/bin/env bats
#
# Integration tests for the server-mode hazards tracked in #114. These drive
# the REAL supervisor (not a mock) with a real SIGINT, so they need a stronger
# isolation contract than the unit-ish tests in test_cc_session.bats:
#
#   1. `unset TMUX` -- TMUX_TMPDIR alone does NOT isolate. A tmux client with
#      $TMUX set uses the socket encoded there and ignores TMUX_TMPDIR.
#   2. The default socket is $TMUX_TMPDIR/tmux-$UID/default -- not
#      $TMUX_TMPDIR/default. Get it wrong and cc-session's own tmux calls land
#      on a different server than the test's, silently.
#   3. A canary ABORTS the run on leak. A canary that records a failure and
#      keeps going is worse than none: the rest of the suite then executes
#      against the host's real tmux server.
#
# Several assertions below deliberately pin CURRENT (buggy) behaviour so the
# fix is observable. Each is marked FIXME(#114) and says what it must become.

setup_file() {
  # Fail the whole file, before any test body runs, if isolation is broken.
  unset TMUX TMUX_PANE
  export TMUX_TMPDIR="${BATS_FILE_TMPDIR}/tmux"
  mkdir -p "$TMUX_TMPDIR"

  local sock="$TMUX_TMPDIR/tmux-$(id -u)/default"
  mkdir -p "$(dirname "$sock")"
  chmod 700 "$(dirname "$sock")"   # tmux refuses a socket dir with laxer perms

  tmux new-session -d -s canary 'sleep 30' || {
    echo "setup_file: cannot start an isolated tmux server" >&2; return 1; }
  if [[ ! -S "$sock" ]]; then
    echo "setup_file: expected socket at $sock -- isolation is not what we think" >&2
    tmux kill-server 2>/dev/null
    return 1
  fi
  tmux kill-server 2>/dev/null || true
}

setup() {
  CC_SESSION="${BATS_TEST_DIRNAME}/../cc-session"
  FAKE_CLAUDE="${BATS_TEST_DIRNAME}/fixtures/fake-claude"
  chmod +x "$FAKE_CLAUDE" "$CC_SESSION"

  unset TMUX TMUX_PANE          # see setup_file
  export CLAUDE_BIN="$FAKE_CLAUDE"
  export TMUX_TMPDIR="${BATS_TEST_TMPDIR}/tmux"
  export TMPDIR="${BATS_TEST_TMPDIR}"
  export CC_SESSION_AUDIT_FILE="${BATS_TEST_TMPDIR}/audit.jsonl"
  export CC_SESSION_NO_REAP=1
  # The real `claude remote-control` is a server: it stays up and the
  # supervisor parks in `wait`. Without this the stub exits on stdin EOF, the
  # supervisor sits in a backoff `sleep` instead, and a SIGINT would not run
  # the trap until that sleep returns -- which is not the behaviour under test.
  export CC_FAKE_CLAUDE_SERVE_FOREVER=1
  mkdir -p "$TMUX_TMPDIR" "$TMPDIR"

  PROJ="${BATS_TEST_TMPDIR}/proj"
  mkdir -p "$PROJ"
}

teardown() {
  [[ -n "${TMUX:-}" ]] && return 1   # never pattern-kill a non-isolated server
  tmux kill-server 2>/dev/null || true
}

# Default name the code builds: cc-YYYYMMDD-<claude-version, dots->dashes>
default_name() {
  printf 'cc-%s-%s' "$(date +%Y%m%d)" \
    "$("$FAKE_CLAUDE" --version | awk '{print $1}' | tr '.' '-')"
}

@test "#114: bare cc-session does NOT open a session named 'claude'" {
  run "$CC_SESSION" -d "$PROJ"
  [ "$status" -eq 0 ]
  sleep 1

  local names; names="$(tmux list-sessions -F '#{session_name}' 2>/dev/null)"
  [[ "$names" == "$(default_name)" ]] || {
    echo "expected '$(default_name)', got '$names'" >&2; return 1; }
  [[ "$names" != "claude" ]]
}

@test "#114: the default name embeds the date, so it cannot re-attach a backbone named 'claude'" {
  # Not a tautology: this pins WHY a bare re-run starts a second daemon
  # instead of re-attaching. If the default ever becomes stable, the
  # eviction hazard below changes shape and this test should be revisited.
  [[ "$(default_name)" =~ ^cc-[0-9]{8}- ]]
  [[ "$(default_name)" != "claude" ]]
}

@test "#114: a second server-mode launch is NOT refused while one is running" {
  # FIXME(#114): this pins the BUG. Once a preflight guard lands, the second
  # launch must be refused (non-zero) and only ONE server-mode session may
  # exist. Invert both assertions then.
  run "$CC_SESSION" -d "$PROJ" claude
  [ "$status" -eq 0 ]
  sleep 1
  [[ "$(tmux show-options -t claude -v '@cc-session-mode' 2>/dev/null)" == "server" ]]

  run "$CC_SESSION" -d "$PROJ"          # bare -> different default name
  [ "$status" -eq 0 ]                   # <-- must become non-zero
  sleep 1

  local n; n="$(tmux list-sessions -F '#{session_name}' 2>/dev/null | wc -l)"
  [ "$n" -eq 2 ]                        # <-- must become 1

  # Both are server-mode: they contend for the same account-level RC
  # environment. The tmux names never collide, so name-based reuse checks
  # cannot catch this.
  [[ "$(tmux show-options -t "$(default_name)" -v '@cc-session-mode' 2>/dev/null)" == "server" ]]
}

@test "#114: SIGINT into a server-mode pane kills the daemon (trap on_term ... INT)" {
  run "$CC_SESSION" -d "$PROJ" claude
  [ "$status" -eq 0 ]
  sleep 2

  local pp; pp="$(tmux list-panes -t claude -F '#{pane_pid}' | head -1)"
  [ -n "$pp" ]

  # Take the child's pid from the supervisor's own state file. Do NOT try to
  # count processes by cmdline: the child runs as `/bin/sh <fake-claude>
  # remote-control`, so an argv[0] anchor on $CLAUDE_BIN never matches (a
  # vacuously-passing assertion), while an unanchored grep also matches the
  # supervisor, whose inlined launch script contains that same string.
  local child; child="$(sed -n 's/^child=//p' "${TMPDIR}/cc-session/claude.pstate")"
  [ -n "$child" ] && [ "$child" != none ]
  kill -0 "$child"                       # alive before the signal

  kill -INT "$pp"
  sleep 3

  # FIXME(#114): the supervisor traps INT exactly like TERM. Ctrl-C in an
  # attached pane therefore tears down RC. If INT is ever ignored (or made
  # to warn instead), pane_dead becomes 0 and this must be inverted.
  [[ "$(tmux list-panes -t claude -F '#{pane_dead}' | head -1)" == "1" ]]
  [[ "$(tmux list-panes -t claude -F '#{pane_dead_status}' | head -1)" == "143" ]]

  # remain-on-exit keeps the session alive around the dead pane, which is
  # exactly why the outage is easy to miss.
  [[ "$(tmux list-sessions -F '#{session_name}' | grep -c '^claude$')" == "1" ]]

  # on_term reaps the child rather than orphaning it.
  ! kill -0 "$child" 2>/dev/null
}

@test "#114: --metrics reports stale gauges for a dead pane (up=0 with uptime>0)" {
  run "$CC_SESSION" -d "$PROJ" claude
  [ "$status" -eq 0 ]
  sleep 2
  kill -INT "$(tmux list-panes -t claude -F '#{pane_pid}' | head -1)"
  sleep 3

  local m; m="$("$CC_SESSION" --metrics 2>/dev/null)"
  [[ "$m" == *'cc_session_up{session="claude"} 0'* ]]

  # FIXME(#71/#114): uptime_seconds is still read from the stale .wstate even
  # though up=0. Any alert keyed on `rc_connected == 0 and up == 1` can never
  # fire in this shape. When fixed, uptime must be 0 here.
  local up; up="$(printf '%s\n' "$m" | sed -n 's/^cc_session_uptime_seconds{session="claude"} //p')"
  [ "${up:-0}" -gt 0 ]
}

@test "#114: tmux -t prefix-matches, and '=' does not prevent it for list-panes" {
  # Not a cc-session bug, but the reason a stale/mistyped target can act on an
  # unrelated session. cc-session uses -t "\$NAME" in --kill and --ctl.
  tmux new-session -d -s claude-tp-DEADBEEF 'sleep 30'

  # With no exact 'claude', BOTH forms resolve to the worker.
  [[ "$(tmux list-panes -t claude -F '#{session_name}' 2>/dev/null | head -1)" == "claude-tp-DEADBEEF" ]]
  [[ "$(tmux list-panes -t '=claude' -F '#{session_name}' 2>/dev/null | head -1)" == "claude-tp-DEADBEEF" ]]

  # An exact session wins when it exists -- which is why this is a latent
  # hazard rather than a constant one.
  tmux new-session -d -s claude 'sleep 30'
  [[ "$(tmux list-panes -t claude -F '#{session_name}' | head -1)" == "claude" ]]
}

@test "the test suite's own tmux isolation holds (canary)" {
  # Regression guard for the bug this file was written alongside: setup()
  # unsets TMUX, so a bare `tmux` here must NOT see the host's server.
  [ -z "${TMUX:-}" ]
  tmux new-session -d -s iso-canary 'sleep 5'
  [[ "$(tmux list-sessions -F '#{session_name}' | grep -c '^iso-canary$')" == "1" ]]

  # And the socket is where we think it is.
  [ -S "$TMUX_TMPDIR/tmux-$(id -u)/default" ]
}
