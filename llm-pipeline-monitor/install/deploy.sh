#!/usr/bin/env bash
# Idempotent deploy for llm-pipeline-monitor as a systemd --user service.
# Re-runnable: installs/updates the package, (re)renders the unit, reloads and restarts.
# Config via install/.env (gate) — see .env.example. No secrets; the only site value is the
# upstream Prometheus URL, which stays in install/.env (never committed).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pkg_dir="$(dirname "$here")"

# --- .env gate (idempotent config) ---
env_file="$here/.env"
if [[ ! -f "$env_file" ]]; then
  echo "llm-pipeline-monitor: no $env_file — copy install/.env.example and adjust, then re-run." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$env_file"
PORT="${PORT:-8896}"
REFRESH="${REFRESH:-5}"
HOST="${HOST:-127.0.0.1}"
# Upstream Prometheus HTTP API base — the one site-specific value (internal endpoint). Required.
PROM_URL="${LLM_PM_PROM_URL:-}"
if [[ -z "$PROM_URL" ]]; then
  echo "llm-pipeline-monitor: LLM_PM_PROM_URL unset in $env_file — set the upstream Prometheus URL." >&2
  exit 1
fi
# Must be a clean http(s) URL: reject whitespace and the sed metacharacters (# & \) that would
# otherwise silently corrupt the unit rendering below into a malformed Environment= line.
if [[ ! "$PROM_URL" =~ ^https?://[^[:space:]#\&\\]+$ ]]; then
  echo "llm-pipeline-monitor: LLM_PM_PROM_URL must be http(s):// with no whitespace or # & \\ chars." >&2
  exit 1
fi

# --- install/update the package (user site) ---
echo "llm-pipeline-monitor: installing package from $pkg_dir"
# pipx gives an isolated venv + a stable console-script on PATH. The host python has no pip module
# and requires-python is >=3.14, so pin the interpreter.
py="$(command -v python3.14 || command -v python3)"
pipx install --force --python "$py" "$pkg_dir" >/dev/null

bin="$(command -v llm-pipeline-monitor || echo "$HOME/.local/bin/llm-pipeline-monitor")"
[[ -x "$bin" ]] || { echo "llm-pipeline-monitor: entry point not found at $bin" >&2; exit 1; }

# --- render + install the unit ---
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
sed -e "s#__BIN__#$bin#g" \
    -e "s#__HOST__#$HOST#g" \
    -e "s#__PORT__#$PORT#g" \
    -e "s#__REFRESH__#$REFRESH#g" \
    -e "s#__PROM_URL__#$PROM_URL#g" \
    "$here/llm-pipeline-monitor.service.template" > "$unit_dir/llm-pipeline-monitor.service"

systemctl --user daemon-reload
systemctl --user enable --now llm-pipeline-monitor.service
systemctl --user restart llm-pipeline-monitor.service

echo "llm-pipeline-monitor: up on http://$HOST:$PORT  (systemctl --user status llm-pipeline-monitor)"
