#!/usr/bin/env bash
set -euo pipefail

BASE_CLOUD="${BASE_CLOUD:-http://127.0.0.1:8785}"
AUTH_HEADER=()
if [[ -n "${VIDEOMEMORY_CLOUD_TOKEN:-}" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${VIDEOMEMORY_CLOUD_TOKEN}")
fi

echo "[1] Cloud VideoMemory Server health"
curl -fsS "$BASE_CLOUD/api/health" >/dev/null

echo "[2] Cloud MCP initialize"
curl -fsS "$BASE_CLOUD/mcp" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' >/dev/null

echo "[3] Trigger intake"
curl -fsS "$BASE_CLOUD/api/event/triggers" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d '{"edge_id":"smoke-edge","event_type":"task_update","note":"smoke test"}' >/dev/null

echo "[4] Queue command"
curl -fsS "$BASE_CLOUD/api/event/commands" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d '{"edge_id":"smoke-edge","action":"ping","args":{}}' >/dev/null

echo "[5] Pull command"
PULL_JSON="$(curl -fsS "$BASE_CLOUD/api/event/commands/pull" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d '{"edge_id":"smoke-edge","max_commands":1}')"
REQ_ID="$(printf '%s' "$PULL_JSON" | sed -n 's/.*"request_id":"\([^"]*\)".*/\1/p')"

if [[ -z "$REQ_ID" ]]; then
  echo "Failed to parse request_id from pull response"
  exit 1
fi

echo "[6] Post result"
curl -fsS "$BASE_CLOUD/api/event/commands/result" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d "{\"edge_id\":\"smoke-edge\",\"request_id\":\"$REQ_ID\",\"status\":\"success\",\"result\":{\"pong\":true}}" >/dev/null

echo "Event Mode cloud smoke test completed."
