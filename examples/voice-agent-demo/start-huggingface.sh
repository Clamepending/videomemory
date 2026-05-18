#!/usr/bin/env bash
set -euo pipefail

SPACE_PORT="${PORT:-7860}"
VIDEOMEMORY_PORT="${VIDEOMEMORY_PORT:-5050}"

export VIDEOMEMORY_BASE_URL="${VIDEOMEMORY_BASE_URL:-http://127.0.0.1:${VIDEOMEMORY_PORT}}"
export VOICE_AGENT_DEMO_PORT="${VOICE_AGENT_DEMO_PORT:-${SPACE_PORT}}"
export VOICE_AGENT_DEMO_HOST="${VOICE_AGENT_DEMO_HOST:-0.0.0.0}"
export VOICE_AGENT_DEMO_PUBLIC_BASE_URL="${VOICE_AGENT_DEMO_PUBLIC_BASE_URL:-http://127.0.0.1:${VOICE_AGENT_DEMO_PORT}}"
export VOICE_AGENT_DEMO_STATE_DIR="${VOICE_AGENT_DEMO_STATE_DIR:-/tmp/videomemory-voice-agent-demo}"
export VIDEO_INGESTOR_MODEL="${VIDEO_INGESTOR_MODEL:-gemini-2.5-flash}"

mkdir -p "$VOICE_AGENT_DEMO_STATE_DIR"

cleanup() {
  if [[ -n "${VIDEOMEMORY_PID:-}" ]]; then
    kill "$VIDEOMEMORY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

cd /app
PORT="$VIDEOMEMORY_PORT" HOST=127.0.0.1 uv run flask_app/app.py &
VIDEOMEMORY_PID="$!"

for _ in $(seq 1 80); do
  if curl -fsS "${VIDEOMEMORY_BASE_URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

curl -fsS "${VIDEOMEMORY_BASE_URL}/api/health" >/dev/null

cd /app/examples/voice-agent-demo
exec node server.mjs
