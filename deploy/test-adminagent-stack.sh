#!/usr/bin/env bash
set -euo pipefail

BASE_VM="${BASE_VM:-http://127.0.0.1:5050}"
BASE_ADM="${BASE_ADM:-http://127.0.0.1:18789}"
BASE_MCP="${BASE_MCP:-http://127.0.0.1:8765}"
TOKEN="${GATEWAY_TOKEN:-change-me}"

echo "[1] Health checks"
curl -fsS "$BASE_VM/api/health" >/dev/null
curl -fsS "$BASE_ADM/health" >/dev/null
curl -fsS "$BASE_MCP/healthz" >/dev/null

echo "[2] MCP initialize"
curl -fsS "$BASE_MCP/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' >/dev/null

echo "[3] Trigger AdminAgent hook"
curl -fsS "$BASE_ADM/hooks/videomemory-alert" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"io_id":"net0","task_id":"smoke","note":"Smoke test alert","task_description":"Smoke test"}' >/dev/null

echo "[4] Verify AdminAgent event log"
curl -fsS "$BASE_ADM/api/events"
echo
echo "AdminAgent stack smoke test completed."
