#!/usr/bin/env bash
set -euo pipefail

BASE_VM="${BASE_VM:-http://127.0.0.1:5050}"
BASE_GW="${BASE_GW:-http://127.0.0.1:18789}"
BASE_MCP="${BASE_MCP:-http://127.0.0.1:8765}"

echo "[1] Health checks"
curl -fsS "$BASE_VM/api/health" >/dev/null
curl -fsS "$BASE_GW/health" >/dev/null
curl -fsS "$BASE_MCP/healthz" >/dev/null

echo "[2] MCP initialize"
curl -fsS "$BASE_MCP/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' >/dev/null

echo "[3] Create RTMP camera (Android-compatible)"
RTMP_RESP="$(curl -fsS "$BASE_VM/api/devices/network/rtmp" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"phone_test"}')"
echo "$RTMP_RESP"

echo "[4] Create SRT camera (low-latency uplink)"
curl -fsS "$BASE_VM/api/devices/network/srt" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"phone_srt"}'
echo

echo "[5] Create WHIP camera (WebRTC ingest)"
curl -fsS "$BASE_VM/api/devices/network/whip" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"phone_webrtc"}'
echo

echo "[6] Trigger gateway wakeup manually"
curl -fsS "$BASE_GW/api/trigger" \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"io_id":"net0","task_id":"test","note":"Smoke test alert","task_description":"Smoke test"}}'

echo
echo "[7] Inspect gateway events"
curl -fsS "$BASE_GW/api/events"
echo
echo "Replica stack smoke test completed."
