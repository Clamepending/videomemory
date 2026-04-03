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
  --google-api-key <key>           Google AI Studio key for VideoMemory + OpenClaw Gemini
  --gemini-api-key <key>           Alias for --google-api-key
  --openrouter-api-key <key>       OpenRouter API key for VideoMemory + OpenClaw
  --video-ingestor-model <model>   VideoMemory model override
  --openclaw-model <model>         OpenClaw primary model override
  --gateway-token <token>          OpenClaw gateway token
  --telegram-bot-token <token>     Telegram bot token
  --telegram-owner-id <chat_id>    Telegram chat id allowlist
  -h, --help                       Show this help

Environment variables are also supported:
  ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, GEMINI_API_KEY,
  OPENROUTER_API_KEY, VIDEO_INGESTOR_MODEL, OPENCLAW_PRIMARY_MODEL,
  OPENCLAW_FALLBACK_MODEL_1, OPENCLAW_FALLBACK_MODEL_2,
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
    --google-api-key|--gemini-api-key)
      export GOOGLE_API_KEY="${2:-}"
      export GEMINI_API_KEY="${2:-}"
      shift 2
      ;;
    --openrouter-api-key)
      export OPENROUTER_API_KEY="${2:-}"
      shift 2
      ;;
    --video-ingestor-model)
      export VIDEO_INGESTOR_MODEL="${2:-}"
      shift 2
      ;;
    --openclaw-model)
      export OPENCLAW_PRIMARY_MODEL="${2:-}"
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

if [[ -n "${GOOGLE_API_KEY:-}" && -z "${GEMINI_API_KEY:-}" ]]; then
  export GEMINI_API_KEY="${GOOGLE_API_KEY}"
fi

if [[ -n "${GEMINI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
  export GOOGLE_API_KEY="${GEMINI_API_KEY}"
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
Set at least one supported model API key before launching.

Examples:
  bash launch_openclaw_with_videomemory.sh --anthropic-api-key your_key_here
  OPENAI_API_KEY=your_key_here bash launch_openclaw_with_videomemory.sh
  GOOGLE_API_KEY=your_key_here bash launch_openclaw_with_videomemory.sh
  OPENROUTER_API_KEY=your_key_here bash launch_openclaw_with_videomemory.sh
EOF
  exit 1
fi

DOCKER_BIN="$(find_docker)"
ensure_docker_running

if [[ -z "${VIDEO_INGESTOR_MODEL:-}" ]]; then
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    export VIDEO_INGESTOR_MODEL="claude-sonnet-4-6"
  elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
    export VIDEO_INGESTOR_MODEL="gpt-4o-mini"
  elif [[ -n "${GOOGLE_API_KEY:-}" || -n "${GEMINI_API_KEY:-}" ]]; then
    export VIDEO_INGESTOR_MODEL="gemini-2.5-flash"
  elif [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    export VIDEO_INGESTOR_MODEL="qwen3-vl-8b"
  fi
fi

if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
  export OPENCLAW_GATEWAY_TOKEN="openclaw-real-dev-token"
fi

if [[ -z "${OPENCLAW_PRIMARY_MODEL:-}" ]]; then
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    export OPENCLAW_PRIMARY_MODEL="anthropic/claude-sonnet-4-6"
    export OPENCLAW_FALLBACK_MODEL_1="anthropic/claude-haiku-4-5"
    export OPENCLAW_FALLBACK_MODEL_2="anthropic/claude-haiku-4-5"
  elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
    export OPENCLAW_PRIMARY_MODEL="openai/gpt-5-mini"
    export OPENCLAW_FALLBACK_MODEL_1="openai/gpt-5-mini"
    export OPENCLAW_FALLBACK_MODEL_2="openai/gpt-5-mini"
  elif [[ -n "${GOOGLE_API_KEY:-}" || -n "${GEMINI_API_KEY:-}" ]]; then
    export OPENCLAW_PRIMARY_MODEL="google/gemini-3-flash-preview"
    export OPENCLAW_FALLBACK_MODEL_1="google/gemini-3-pro-preview"
    export OPENCLAW_FALLBACK_MODEL_2="google/gemini-3-pro-preview"
  elif [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    export OPENCLAW_PRIMARY_MODEL="openrouter/anthropic/claude-sonnet-4-5"
    export OPENCLAW_FALLBACK_MODEL_1="openrouter/google/gemini-2.0-flash-vision:free"
    export OPENCLAW_FALLBACK_MODEL_2="openrouter/google/gemini-2.0-flash-vision:free"
  fi
else
  if [[ -z "${OPENCLAW_FALLBACK_MODEL_1:-}" ]]; then
    export OPENCLAW_FALLBACK_MODEL_1="${OPENCLAW_PRIMARY_MODEL}"
  fi
  if [[ -z "${OPENCLAW_FALLBACK_MODEL_2:-}" ]]; then
    export OPENCLAW_FALLBACK_MODEL_2="${OPENCLAW_PRIMARY_MODEL}"
  fi
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
