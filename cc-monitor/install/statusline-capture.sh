#!/usr/bin/env bash
# cc-monitor statusLine capture — the ONLY local channel that carries the real context window.
#
# Claude Code invokes `statusLine.command` once per TUI render, handing it a JSON payload on stdin
# and taking the command's stdout as the rendered line. That payload carries
# `context_window.context_window_size` and a `model.id` bearing the `[1m]` suffix — the one place
# the suffix survives locally. The transcript's `message.model` and the OTel `api_request` event's
# `model` attribute are both stripped, and no ANTHROPIC_DEFAULT_* env need exist at all (the CLI
# appends `[1m]` at runtime from an account-level entitlement predicate). Without this capture,
# cc-monitor cannot tell a 1M session from a 200k one.
#
# Only TUI sessions render a statusLine; `sdk-cli` workers never call this. cc-monitor generalises
# a sample across same-family sessions (single-account, single-host boundary) — see window.py.
#
# Install: settings.json `statusLine.command` -> this script (deploy.sh wires it).
# To keep an existing status line, set CC_MONITOR_STATUSLINE_CHAIN to a command that reads the
# same payload on stdin and prints the line; its stdout replaces the default one below.
set -uo pipefail

payload="$(cat)"
[ -n "$payload" ] || exit 0

line="$(CC_MONITOR_STATUSLINE_DIR="${CC_MONITOR_STATUSLINE_DIR:-$HOME/.claude/cc-monitor-statusline}" \
python3 -c '
import json, os, sys, tempfile, time

raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    raise SystemExit(0)  # a malformed payload must never break the status line

sid = d.get("session_id")
cw = d.get("context_window") if isinstance(d.get("context_window"), dict) else {}
model = d.get("model") if isinstance(d.get("model"), dict) else {}
effort = d.get("effort") if isinstance(d.get("effort"), dict) else {}
size = cw.get("context_window_size")

# Only the display-safe scalars are persisted. The payload also carries cwd/workspace/cost — none
# of which cc-monitor needs from here, and repo paths are what we least want written twice.
rec = {
    "session_id": sid,
    "win": size if isinstance(size, int) and size > 0 else None,
    "model_id": model.get("id") if isinstance(model.get("id"), str) else None,
    "effort": effort.get("level") if isinstance(effort.get("level"), str) else None,
    "ts": time.time(),
}

# `sid` doubles as a filename: reject anything that is not the plain uuid Claude Code emits.
ok_sid = isinstance(sid, str) and sid and "/" not in sid and not sid.startswith(".")


def unchanged(dest):
    """True when a recent sample already records the same facts — a render happens several times a
    second, and none of these scalars change that often."""
    try:
        if time.time() - os.path.getmtime(dest) > 60:
            return False
        with open(dest) as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return False
    return all(old.get(k) == rec[k] for k in ("win", "model_id", "effort"))


if ok_sid and (rec["win"] or rec["model_id"]):
    out = os.environ["CC_MONITOR_STATUSLINE_DIR"]
    dest = os.path.join(out, sid + ".json")
    try:
        os.makedirs(out, exist_ok=True)
        if not unchanged(dest):
            # Atomic per-session write: concurrent renders across sessions never touch the same
            # file, so there is no read-modify-write race on a shared blob.
            fd, tmp = tempfile.mkstemp(dir=out, prefix=".tmp-")
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(rec, fh)
                os.replace(tmp, dest)  # mkstemp already created it 0600
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except OSError:
        pass  # capture is best-effort; the render below must still happen

name = model.get("display_name") or model.get("id") or "claude"
lvl = effort.get("level")
used = cw.get("used_percentage")
bits = [str(name)]
if lvl:
    bits.append(str(lvl))
if isinstance(used, (int, float)):
    bits.append(f"{used:.0f}%")
print(" · ".join(bits))
' <<<"$payload" 2>/dev/null)"

if [ -n "${CC_MONITOR_STATUSLINE_CHAIN:-}" ]; then
  printf '%s' "$payload" | sh -c "$CC_MONITOR_STATUSLINE_CHAIN" 2>/dev/null || true
else
  printf '%s\n' "$line"
fi
exit 0
