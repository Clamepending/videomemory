#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.real-openclaw.yml"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd curl
require_cmd python3

if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
  cat >&2 <<'EOF'
Set either ANTHROPIC_API_KEY or OPENAI_API_KEY before launching.

Example:
  ANTHROPIC_API_KEY=your_key_here TELEGRAM_BOT_TOKEN=your_bot_token OPENCLAW_GATEWAY_TOKEN=openclaw-real-dev-token bash docs/launch-openclaw-real.sh
EOF
  exit 1
fi

if [[ -z "${VIDEO_INGESTOR_MODEL:-}" ]]; then
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    export VIDEO_INGESTOR_MODEL="claude-sonnet-4-6"
  else
    export VIDEO_INGESTOR_MODEL="gpt-4o-mini"
  fi
fi

resolve_telegram_owner_id() {
  local updates_json
  updates_json="$(curl -fsSL "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates")"
  python3 - "$updates_json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
ids = []
for item in payload.get("result", []):
    for key in ("message", "edited_message", "channel_post", "my_chat_member"):
        chat = item.get(key, {}).get("chat", {})
        chat_id = chat.get("id")
        if chat_id is not None:
            ids.append(str(chat_id))
if ids:
    print(ids[-1])
PY
}

wait_for_videomemory() {
  echo "Waiting for VideoMemory to become healthy..."
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:5050/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "VideoMemory did not become healthy in time." >&2
  exit 1
}

cleanup_demo_camera() {
  local devices_json
  devices_json="$(curl -fsSL "http://127.0.0.1:5050/api/devices")"
  python3 - "$devices_json" <<'PY'
import json
import sys
import urllib.request

payload = json.loads(sys.argv[1])
devices = payload.get("devices", {})
targets = []
for entries in devices.values():
    for device in entries:
        name = str(device.get("name", ""))
        url = str(device.get("url", ""))
        source = str(device.get("source", ""))
        if source != "network":
            continue
        if (
            "Demo Red Marker Camera" in name
            or "demo-camera:8080/snapshot.jpg" in url
            or "18081/snapshot.jpg" in url
        ):
            io_id = device.get("io_id")
            if io_id:
                targets.append(str(io_id))

for io_id in targets:
    req = urllib.request.Request(
        f"http://127.0.0.1:5050/api/devices/network/{io_id}",
        method="DELETE",
    )
    with urllib.request.urlopen(req) as resp:
        sys.stdout.write(resp.read().decode("utf-8"))
        sys.stdout.write("\n")
PY
}

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -z "${OPENCLAW_TELEGRAM_OWNER_ID:-}" ]]; then
  echo "Telegram bot token provided without OPENCLAW_TELEGRAM_OWNER_ID."
  echo "Trying to resolve the owner chat automatically from the bot's recent updates..."
  OPENCLAW_TELEGRAM_OWNER_ID="$(resolve_telegram_owner_id || true)"
  export OPENCLAW_TELEGRAM_OWNER_ID
  if [[ -z "${OPENCLAW_TELEGRAM_OWNER_ID}" ]]; then
    cat >&2 <<'EOF'
Could not determine OPENCLAW_TELEGRAM_OWNER_ID automatically.
Send any message to your Telegram bot once, then rerun this command.
EOF
    exit 1
  fi
  echo "Using Telegram owner chat id: ${OPENCLAW_TELEGRAM_OWNER_ID}"
fi

echo "Launching bundled OpenClaw + VideoMemory stack..."
docker compose -f "$COMPOSE_FILE" up -d --build

wait_for_videomemory
cleanup_demo_camera

cat <<EOF

OpenClaw:   http://localhost:18889/
VideoMemory: http://localhost:5050/devices
Gateway token: ${OPENCLAW_GATEWAY_TOKEN:-openclaw-real-dev-token}
EOF
