#!/usr/bin/env bash
set -euo pipefail

BASE_VM="${BASE_VM:-http://127.0.0.1:5050}"
BASE_ADAPTER="${BASE_ADAPTER:-http://127.0.0.1:8091}"
BASE_MCP="${BASE_MCP:-http://127.0.0.1:8765}"
BASE_OC="${BASE_OC:-http://127.0.0.1:18789}"
LAPTOP_HOST="${LAPTOP_HOST:-127.0.0.1}"
DEVICE_NAME="${DEVICE_NAME:-phone_demo_live}"

echo "[1/7] Health checks"
curl -fsS "$BASE_VM/api/health" >/dev/null
curl -fsS "$BASE_ADAPTER/healthz" >/dev/null
curl -fsS "$BASE_MCP/healthz" >/dev/null

echo "[2/7] MCP initialize"
curl -fsS "$BASE_MCP/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"phone-demo-smoke","version":"0.1"}}}' >/dev/null

echo "[3/7] Ensure OpenClaw gateway is reachable"
curl -fsS "$BASE_OC/" >/dev/null

echo "[4/7] Inject synthetic alert through adapter"
curl -fsS -X POST "$BASE_ADAPTER/videomemory-alert" \
  -H 'Content-Type: application/json' \
  -d '{"source":"videomemory","event_type":"task_update","edge_id":"demo-edge","task_id":999,"io_id":"net-demo","task_description":"demo","note":"synthetic alert from demo script"}' >/dev/null

echo "[5/7] Create RTMP camera for phone"
CREATE_JSON="$(curl -fsS -X POST "$BASE_VM/api/devices/network/rtmp" \
  -H 'Content-Type: application/json' \
  -d "{\"device_name\":\"$DEVICE_NAME\"}")"

STREAM_PATH="$(printf '%s' "$CREATE_JSON" | sed -n 's/.*"rtsp_pull_url":"[^"]*\/live\/\([^"]*\)".*/\1/p')"
if [[ -z "$STREAM_PATH" ]]; then
  echo "Failed to parse stream path from camera creation response:"
  echo "$CREATE_JSON"
  exit 1
fi

PHONE_RTMP_URL="rtmp://${LAPTOP_HOST}:1935/live/${STREAM_PATH}"

echo "[6/7] Check OpenClaw model auth precondition"
if docker exec openclaw sh -lc 'test -n "$ANTHROPIC_API_KEY" || test -n "$OPENAI_API_KEY" || test -n "$OPENROUTER_API_KEY"' >/dev/null 2>&1; then
  echo "OpenClaw model key appears configured."
else
  echo "WARNING: No model API key visible in openclaw container env."
  echo "DM/hook wakeups will enqueue but the agent cannot respond until a key is configured."
fi

echo "[7/7] Demo outputs"
echo "Phone streaming URL: $PHONE_RTMP_URL"
echo "VideoMemory UI:       http://${LAPTOP_HOST}:5050"
echo "OpenClaw UI:          $BASE_OC"
echo "Adapter recent events: ${BASE_ADAPTER}/recent?limit=10"
echo
echo "Script completed."
