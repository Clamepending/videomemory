#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.real-openclaw.yml"

find_docker() {
  if [[ -n "${DOCKER_BIN:-}" ]]; then
    printf '%s\n' "$DOCKER_BIN"
    return
  fi
  if command -v docker >/dev/null 2>&1; then
    command -v docker
    return
  fi
  if [[ -x /opt/homebrew/bin/docker ]]; then
    printf '%s\n' "/opt/homebrew/bin/docker"
    return
  fi
  echo "Missing required command: docker" >&2
  exit 1
}

docker_ready() {
  "$DOCKER_BIN" info >/dev/null 2>&1
}

if [[ $# -ne 0 ]]; then
  echo "This script takes no positional arguments." >&2
  exit 1
fi

if [[ ! -r /dev/tty ]]; then
  echo "Run this script from an interactive terminal." >&2
  exit 1
fi

DOCKER_BIN="$(find_docker)"
if ! docker_ready; then
  echo "Docker is not ready. Start Docker first, then rerun this command." >&2
  exit 1
fi
container_id="$("$DOCKER_BIN" compose -f "$COMPOSE_FILE" ps -q openclaw)"

if [[ -z "$container_id" ]]; then
  cat >&2 <<'EOF'
OpenClaw is not running.
Start the stack first:
  bash docs/launch-openclaw-real.sh
EOF
  exit 1
fi

exec </dev/tty >/dev/tty 2>/dev/tty
stty sane 2>/dev/null || true
exec "$DOCKER_BIN" exec \
  -e TERM="${TERM:-xterm-256color}" \
  -it "$container_id" \
  sh -lc "exec openclaw tui --url ws://127.0.0.1:18789 --token '${OPENCLAW_GATEWAY_TOKEN:-openclaw-real-dev-token}' --session main"
