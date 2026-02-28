#!/usr/bin/env bash
set -euo pipefail

BASE_CLOUD="${BASE_CLOUD:-http://127.0.0.1:8785}"
EDGE_ID="${EDGE_ID:-smoke-edge-mcp}"
AUTH_HEADER=()
if [[ -n "${VIDEOMEMORY_CLOUD_TOKEN:-}" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${VIDEOMEMORY_CLOUD_TOKEN}")
fi

echo "[1] MCP health"
curl -fsS "$BASE_CLOUD/healthz" >/dev/null

echo "[2] MCP initialize"
curl -fsS "$BASE_CLOUD/mcp" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' >/dev/null

echo "[3] Enqueue command via MCP"
curl -fsS "$BASE_CLOUD/mcp" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"id\":2,
    \"method\":\"tools/call\",
    \"params\":{
      \"name\":\"enqueue_edge_command\",
      \"arguments\":{\"edge_id\":\"$EDGE_ID\",\"action\":\"ping\",\"args\":{}}
    }
  }" >/dev/null

echo "[4] Pull command via edge queue endpoint"
PULL_JSON="$(curl -fsS "$BASE_CLOUD/api/event/commands/pull" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d "{\"edge_id\":\"$EDGE_ID\",\"max_commands\":1}")"

REQ_ID="$(printf '%s' "$PULL_JSON" | sed -n 's/.*"request_id":"\([^"]*\)".*/\1/p')"
if [[ -z "$REQ_ID" ]]; then
  echo "Failed to parse request_id from pull response"
  exit 1
fi

echo "[5] Post result and verify via MCP"
curl -fsS "$BASE_CLOUD/api/event/commands/result" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d "{\"edge_id\":\"$EDGE_ID\",\"request_id\":\"$REQ_ID\",\"status\":\"success\",\"result\":{\"pong\":true}}" >/dev/null

curl -fsS "$BASE_CLOUD/mcp" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"id\":3,
    \"method\":\"tools/call\",
    \"params\":{
      \"name\":\"list_recent_results\",
      \"arguments\":{\"edge_id\":\"$EDGE_ID\",\"limit\":5}
    }
  }" >/dev/null

echo "Event Mode MCP smoke test completed."
