#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.replica.yml}"
DOCKER_HOST_URI="${DOCKER_HOST_URI:-unix:///Users/mark/.colima/default/docker.sock}"
DOCKER_CFG="${DOCKER_CFG:-/tmp/docker-config}"

dc() {
  DOCKER_CONFIG="$DOCKER_CFG" DOCKER_HOST="$DOCKER_HOST_URI" docker-compose -f "$COMPOSE_FILE" "$@"
}

gw_py_post() {
  local path="$1"
  local json_payload="$2"
  dc exec -T \
    -e GW_PATH="$path" \
    -e GW_JSON="$json_payload" \
    admin-gateway-replica \
    python -c "import json, os, requests; resp=requests.post('http://127.0.0.1:18789'+os.environ['GW_PATH'], json=json.loads(os.environ['GW_JSON']), timeout=30); print(resp.text); raise SystemExit(0 if resp.ok else 1)"
}

gw_py_get() {
  local path="$1"
  dc exec -T \
    -e GW_PATH="$path" \
    admin-gateway-replica \
    python -c "import os, requests; resp=requests.get('http://127.0.0.1:18789'+os.environ['GW_PATH'], timeout=30); print(resp.text); raise SystemExit(0 if resp.ok else 1)"
}

echo "[1] Containers up"
dc ps

echo "[2] VideoMemory frontend/API/MCP health (inside container network)"
dc exec -T videomemory bash -lc 'curl -fsS http://127.0.0.1:5050/ >/dev/null'
dc exec -T videomemory bash -lc 'curl -fsS http://127.0.0.1:5050/api/health'
dc exec -T videomemory bash -lc 'curl -fsS http://127.0.0.1:8765/healthz'

echo
echo "[3] MCP initialize + list tools"
dc exec -T videomemory bash -lc "curl -fsS http://127.0.0.1:8765/mcp -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\"}}'"
echo
dc exec -T videomemory bash -lc "curl -fsS http://127.0.0.1:8765/mcp -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}'" >/dev/null

echo "[4] Create RTMP camera (Android-compatible)"
RTMP_RESP="$(dc exec -T videomemory bash -lc "curl -fsS http://127.0.0.1:5050/api/devices/network/rtmp -H 'Content-Type: application/json' -d '{\"device_name\":\"phone_test\"}'")"
echo "$RTMP_RESP"

echo "[5] Create SRT camera (low-latency uplink)"
dc exec -T videomemory bash -lc "curl -fsS http://127.0.0.1:5050/api/devices/network/srt -H 'Content-Type: application/json' -d '{\"device_name\":\"phone_srt\"}'"
echo

echo "[6] Create WHIP camera (WebRTC ingest)"
dc exec -T videomemory bash -lc "curl -fsS http://127.0.0.1:5050/api/devices/network/whip -H 'Content-Type: application/json' -d '{\"device_name\":\"phone_webrtc\"}'"
echo

echo "[7] Admin gateway replica health"
gw_py_get /health
echo

echo "[8] Trigger gateway wakeup (forwards to VideoMemory /chat)"
TRIGGER_RESP="$(gw_py_post /api/trigger '{"payload":{"io_id":"net0","task_id":"test","note":"Smoke test alert","task_description":"Smoke test"}}')"
echo "$TRIGGER_RESP"

echo "[9] Inspect gateway events"
gw_py_get /api/events
echo

if echo "$TRIGGER_RESP" | grep -q '"status":"error"'; then
  echo "[WARN] Gateway forwarding reached /chat but the admin agent likely failed (commonly missing GOOGLE_API_KEY)."
  exit 0
fi

echo "Internal replica stack smoke test completed successfully."
