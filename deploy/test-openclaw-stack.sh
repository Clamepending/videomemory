#!/usr/bin/env bash
set -euo pipefail

BASE_VM="${BASE_VM:-http://127.0.0.1:5050}"
BASE_OC="${BASE_OC:-http://127.0.0.1:18789}"
BASE_MCP="${BASE_MCP:-http://127.0.0.1:8765}"

echo "[1] Health checks"
curl -fsS "$BASE_VM/api/health" >/dev/null
curl -fsS "$BASE_MCP/healthz" >/dev/null
curl -fsS "$BASE_OC/" >/dev/null || true

echo "[2] MCP initialize"
curl -fsS "$BASE_MCP/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' >/dev/null

echo "[3] Create RTMP camera"
curl -fsS "$BASE_VM/api/devices/network/rtmp" \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"phone_test_openclaw"}' >/dev/null

echo "OpenClaw stack smoke test completed."
