#!/usr/bin/env bash
# Idempotent deploy of a DEV/staging cc-monitor instance ALONGSIDE prod.
#
# Prod (deploy.sh) is pipx from a fixed checkout on PORT/HOST. This dev instance instead runs the
# CURRENT checkout via an *editable* venv, so it previews whatever branch is checked out here —
# restart to pick up new commits. It binds a separate port (PORT_DEV) and an isolated config file
# so staging edits never touch the prod instance. Typical use: a dedicated git worktree
# (e.g. `git worktree add ../.wt/cc-monitor-dev <branch>`), then run this from inside it.
#
# Edge: front it behind your reverse proxy at a single-label host (a nested dev.cc-monitor.<domain>
# would need its own wildcard cert; single-label wildcards don't nest).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pkg_dir="$(dirname "$here")"

env_file="$here/.env"
# shellcheck disable=SC1090
[[ -f "$env_file" ]] && source "$env_file"
HOST="${HOST:-127.0.0.1}"
PORT_DEV="${PORT_DEV:-8898}"
REFRESH="${REFRESH:-3}"
# Dev defaults to NO embedded OTLP sink (OTEL_SINK=0): prod owns the single :4318 receiver per host.
# Set OTEL_SINK=1 (+ optional OTEL_PORT) in install/.env to give dev the sink instead.
OTEL_SINK="${OTEL_SINK:-0}"
if [[ "$OTEL_SINK" == "0" ]]; then otel_args="--no-otel-sink"; else otel_args=""; fi
[[ -n "${OTEL_PORT:-}" ]] && otel_args="${otel_args:+$otel_args }--otel-port $OTEL_PORT"

state_dir="$HOME/.local/share/cc-monitor-dev"
venv="$state_dir/venv"
config="$state_dir/config.json"
mkdir -p "$state_dir"

# editable venv from THIS checkout (host python often lacks pip, so use a venv, not pipx)
py="$(command -v python3.14 || command -v python3)"
[[ -d "$venv" ]] || "$py" -m venv "$venv"
"$venv/bin/pip" -q install -e "$pkg_dir"
bin="$venv/bin/cc-monitor"

unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
sed -e "s#__BIN__#$bin#g" \
    -e "s#__HOST__#$HOST#g" \
    -e "s#__PORT__#$PORT_DEV#g" \
    -e "s#__REFRESH__#$REFRESH#g" \
    -e "s#__CONFIG__#$config#g" \
    -e "s#__OTEL_ARGS__#$otel_args#g" \
    "$here/cc-monitor-dev.service.template" > "$unit_dir/cc-monitor-dev.service"

systemctl --user daemon-reload
systemctl --user enable --now cc-monitor-dev.service
systemctl --user restart cc-monitor-dev.service

echo "cc-monitor-dev: up on http://$HOST:$PORT_DEV  (systemctl --user status cc-monitor-dev)"
