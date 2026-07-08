#!/usr/bin/env bash
# Idempotent enable/disable of Claude Code's OTel export for cc-monitor's per-session effort.
#
# WHAT: patches the `env` block of Claude Code's settings.json so EVERY session (RC bridge /
#   `claude --resume` / GUI) exports its `api_request` telemetry to cc-monitor's loopback OTLP sink.
#   Claude Code applies this env block INTERNALLY at startup, so one edit covers all spawn paths.
# WHY as a settings.json env block (not shell env): only this reaches `claude --resume`/RC workers
#   whose exec env is frozen (the same mechanism behind the window resume-fix, PR #99).
# SAFE: only the OTEL_*/telemetry keys are touched — existing env keys (ANTHROPIC_DEFAULT_*, PATH)
#   are preserved. A timestamped backup is written. `--disable` removes exactly the keys this adds.
#
# Passive side-channel: no Anthropic auth, no extra API call, no token cost. The endpoint is
# loopback; the sink strips identity attributes and writes an 0600 sidecar. Per-session detail
# never enters Prometheus.
#
# NOTE: env changes apply to sessions started AFTER the edit (env is injected at startup). Existing
# sessions keep their old config until they restart.
#
# Usage:
#   enable-otel.sh                 # enable (default endpoint http://127.0.0.1:4318)
#   enable-otel.sh --disable       # remove the OTel keys (rollback)
#   enable-otel.sh --endpoint URL  # non-default sink endpoint
#   enable-otel.sh --settings PATH # non-default settings.json (default ~/.claude/settings.json)
#   enable-otel.sh --dry-run       # print the resulting env-key diff, write nothing
set -euo pipefail

endpoint="http://127.0.0.1:4318"
settings="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
action="enable"
dry=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --disable) action="disable" ;;
    --endpoint) endpoint="$2"; shift ;;
    --settings) settings="$2"; shift ;;
    --dry-run) dry="1" ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

py="$(command -v python3.14 || command -v python3)"
ACTION="$action" ENDPOINT="$endpoint" SETTINGS="$settings" DRY="$dry" "$py" - <<'PY'
import json, os, sys, time

path = os.environ["SETTINGS"]
action = os.environ["ACTION"]
endpoint = os.environ["ENDPOINT"]
dry = os.environ.get("DRY")

# The exact keys this tool manages — nothing else in `env` is touched. metrics=none: the sink only
# consumes the api_request LOG event, so we don't ship metrics (less traffic, and metrics keyed by
# session.id must never reach a TSDB anyway).
KEYS = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
}

try:
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        print(f"error: {path} is not a JSON object", file=sys.stderr); sys.exit(1)
except FileNotFoundError:
    data = {}
except (OSError, ValueError) as e:
    print(f"error reading {path}: {e}", file=sys.stderr); sys.exit(1)

env = data.get("env")
if not isinstance(env, dict):
    env = {}
before = {k: env.get(k) for k in KEYS}

if action == "enable":
    env.update(KEYS)
else:  # disable — remove exactly our keys, leave the rest of the env block intact
    for k in KEYS:
        env.pop(k, None)
data["env"] = env
after = {k: env.get(k) for k in KEYS}

changed = before != after
for k in KEYS:
    b, a = before.get(k), after.get(k)
    mark = " " if b == a else "*"
    print(f"  {mark} {k}: {b!r} -> {a!r}")
if not changed:
    print(f"already {'enabled' if action == 'enable' else 'disabled'} — no change.")
    sys.exit(0)
if dry:
    print("[dry-run] no file written.")
    sys.exit(0)

bak = f"{path}.bak.{int(time.time())}"
if os.path.exists(path):
    with open(path) as fh:
        os.write(os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), fh.read().encode())
    print(f"backup: {bak}")

tmp = path + ".tmp"
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
print(f"{'enabled' if action == 'enable' else 'disabled'}: {path}")
print("note: applies to sessions started AFTER this edit (env is injected at startup).")
PY
