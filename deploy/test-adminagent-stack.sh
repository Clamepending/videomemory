#!/usr/bin/env bash
set -euo pipefail

BASE_VM="${BASE_VM:-http://127.0.0.1:5050}"
BASE_ADM="${BASE_ADM:-http://127.0.0.1:18889}"
BASE_MCP="${BASE_MCP:-http://127.0.0.1:8765}"
TOKEN="${OPENCLAW_GATEWAY_TOKEN:-${GATEWAY_TOKEN:-change-me}}"
BOT_ID="${VIDEOMEMORY_OPENCLAW_BOT_ID:-videomemory}"

echo "[1] Health checks"
curl -fsS "$BASE_VM/api/health" >/dev/null
curl -fsS "$BASE_ADM/health" >/dev/null
curl -fsS "$BASE_MCP/healthz" >/dev/null

echo "[2] MCP initialize"
curl -fsS "$BASE_MCP/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' >/dev/null

echo "[3] Ensure BOT_ID exists (if multi-bot mode is enabled)"
BOTS_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE_ADM/api/bots" || true)"
if [[ "$BOTS_STATUS" == "200" ]]; then
  curl -sS -o /tmp/simpleagent-create-bot.out -w '%{http_code}' \
    -X POST "$BASE_ADM/api/bots" \
    -H 'Content-Type: application/json' \
    -d "{\"bot_id\":\"$BOT_ID\",\"name\":\"VideoMemory\",\"model\":\"gpt-5\"}" \
    | grep -Eq '^(200|409)$'
else
  echo "Skipping bot create: /api/bots returned $BOTS_STATUS"
fi

echo "[4] Trigger AdminAgent hook"
curl -fsS "$BASE_ADM/hooks/videomemory-alert" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"bot_id\":\"$BOT_ID\",\"io_id\":\"net0\",\"task_id\":\"smoke\",\"note\":\"Smoke test alert\",\"task_description\":\"Smoke test\"}" >/dev/null

echo "[5] Verify AdminAgent event log"
curl -fsS "$BASE_ADM/api/events"
echo

echo "AdminAgent stack smoke test completed."
