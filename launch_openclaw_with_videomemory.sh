#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

ensure_docker_running() {
  if docker_ready; then
    return
  fi

  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Docker Desktop is not ready. Opening Docker..."
    open -a Docker >/dev/null 2>&1 || true
    for _ in $(seq 1 90); do
      if docker_ready; then
        return
      fi
      sleep 2
    done
    cat >&2 <<'EOF'
Docker Desktop did not become ready in time.
Open Docker Desktop, wait until the engine says it is running, then rerun this command.
EOF
    exit 1
  fi

  cat >&2 <<'EOF'
Docker is installed but the daemon is not running.
Start Docker, then rerun this command.
EOF
  exit 1
}

wait_for_url() {
  local label="$1"
  local url="$2"
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "$label did not become healthy in time." >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  bash launch_openclaw_with_videomemory.sh [options]

Options:
  --anthropic-api-key <key>        Anthropic API key for OpenClaw + VideoMemory
  --openai-api-key <key>           OpenAI API key for OpenClaw + VideoMemory
  --video-ingestor-model <model>   VideoMemory model override
  --gateway-token <token>          OpenClaw gateway token
  --telegram-bot-token <token>     Telegram bot token
  --telegram-owner-id <chat_id>    Telegram chat id allowlist
  -h, --help                       Show this help

Environment variables are also supported:
  ANTHROPIC_API_KEY, OPENAI_API_KEY, VIDEO_INGESTOR_MODEL,
  OPENCLAW_GATEWAY_TOKEN, TELEGRAM_BOT_TOKEN, OPENCLAW_TELEGRAM_OWNER_ID
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --anthropic-api-key)
      export ANTHROPIC_API_KEY="${2:-}"
      shift 2
      ;;
    --openai-api-key)
      export OPENAI_API_KEY="${2:-}"
      shift 2
      ;;
    --video-ingestor-model)
      export VIDEO_INGESTOR_MODEL="${2:-}"
      shift 2
      ;;
    --gateway-token)
      export OPENCLAW_GATEWAY_TOKEN="${2:-}"
      shift 2
      ;;
    --telegram-bot-token)
      export TELEGRAM_BOT_TOKEN="${2:-}"
      shift 2
      ;;
    --telegram-owner-id)
      export OPENCLAW_TELEGRAM_OWNER_ID="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
Set either ANTHROPIC_API_KEY or OPENAI_API_KEY before launching.

Examples:
  bash launch_openclaw_with_videomemory.sh --anthropic-api-key your_key_here
  OPENAI_API_KEY=your_key_here bash launch_openclaw_with_videomemory.sh
EOF
  exit 1
fi

DOCKER_BIN="$(find_docker)"
ensure_docker_running

if [[ -z "${VIDEO_INGESTOR_MODEL:-}" ]]; then
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    export VIDEO_INGESTOR_MODEL="claude-sonnet-4-6"
  else
    export VIDEO_INGESTOR_MODEL="gpt-4o-mini"
  fi
fi

if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
  export OPENCLAW_GATEWAY_TOKEN="openclaw-real-dev-token"
fi

echo "Launching bundled OpenClaw + VideoMemory stack..."
"$DOCKER_BIN" compose -f "$COMPOSE_FILE" up -d --build videomemory openclaw

echo "Waiting for VideoMemory..."
wait_for_url "VideoMemory" "http://127.0.0.1:5050/api/health"

echo "Waiting for OpenClaw..."
wait_for_url "OpenClaw" "http://127.0.0.1:18889/healthz"

cat <<EOF

VideoMemory UI:
  http://localhost:5050/devices

OpenClaw dashboard:
  http://localhost:18889/?token=${OPENCLAW_GATEWAY_TOKEN}

OpenClaw raw UI:
  http://localhost:18889/

Notes:
  - The bundled stack already mounts the OpenClaw config that wires VideoMemory webhooks.
  - The dashboard link above includes the gateway token so you can open it directly.
  - If you want the in-container TUI after launch, run:
      OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN} bash docs/launch-openclaw-real-tui.sh
EOF
