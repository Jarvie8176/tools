#!/usr/bin/env bash
# Idempotent deploy for cc-monitor as a systemd --user service.
# Re-runnable: installs/updates the package, (re)renders the unit, reloads and restarts.
# Config via install/.env (gate) — see .env.example. No secrets required.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pkg_dir="$(dirname "$here")"

# --- .env gate (idempotent config) ---
env_file="$here/.env"
if [[ ! -f "$env_file" ]]; then
  echo "cc-monitor: no $env_file — copy install/.env.example and adjust, then re-run." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$env_file"
PORT="${PORT:-8899}"
REFRESH="${REFRESH:-3}"
HOST="${HOST:-127.0.0.1}"
# Optional textfile metrics target (Alloy/node-exporter textfile collector dir). Unset = disabled;
# an empty Environment= leaves paths.METRICS_FILE "" so cc-monitor writes no textfile.
METRICS_FILE="${CC_MONITOR_METRICS_FILE:-}"
# Prod owns the per-host :4318 OTLP receiver by default (per-session effort). Set OTEL_SINK=0
# in install/.env (→ --no-otel-sink) if another cc-monitor instance owns the sink on this host.
OTEL_SINK="${OTEL_SINK:-1}"
if [[ "$OTEL_SINK" == "0" ]]; then otel_args="--no-otel-sink"; else otel_args=""; fi
[[ -n "${OTEL_PORT:-}" ]] && otel_args="${otel_args:+$otel_args }--otel-port $OTEL_PORT"

# --- install/update the package (user site) ---
echo "cc-monitor: installing package from $pkg_dir"
# pipx gives an isolated venv + a stable console-script on PATH. It is the supported installer
# here: the host python has no pip module, and requires-python is >=3.14, so pin the interpreter.
py="$(command -v python3.14 || command -v python3)"
pipx install --force --python "$py" "$pkg_dir" >/dev/null

bin="$(command -v cc-monitor || echo "$HOME/.local/bin/cc-monitor")"
[[ -x "$bin" ]] || { echo "cc-monitor: entry point not found at $bin" >&2; exit 1; }


# --- render + install the unit ---
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
sed -e "s#__CCMONITOR_BIN__#$bin#g" \
    -e "s#__HOST__#$HOST#g" \
    -e "s#__PORT__#$PORT#g" \
    -e "s#__REFRESH__#$REFRESH#g" \
    -e "s#__METRICS_FILE__#$METRICS_FILE#g" \
    -e "s#__OTEL_ARGS__#$otel_args#g" \
    "$here/cc-monitor.service.template" > "$unit_dir/cc-monitor.service"

systemctl --user daemon-reload
systemctl --user enable --now cc-monitor.service
systemctl --user restart cc-monitor.service

echo "cc-monitor: up on http://$HOST:$PORT  (systemctl --user status cc-monitor)"
