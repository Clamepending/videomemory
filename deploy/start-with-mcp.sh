#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MEDIAMTX_PID=""
MCP_PID=""

cleanup() {
  for pid in "$MCP_PID" "$MEDIAMTX_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

echo "Starting MediaMTX (RTMP :1935, RTSP :8554)..."
/usr/local/bin/mediamtx "$REPO_ROOT/rtmp-server/mediamtx.yml" &
MEDIAMTX_PID=$!

echo "Starting VideoMemory MCP HTTP server (:${VIDEOMEMORY_MCP_PORT:-8765})..."
uv run python -m videomemory.mcp_server \
  --transport http \
  --host 0.0.0.0 \
  --port "${VIDEOMEMORY_MCP_PORT:-8765}" \
  --api-base-url "http://127.0.0.1:${PORT:-5050}" &
MCP_PID=$!

sleep 1
for pid in "$MEDIAMTX_PID" "$MCP_PID"; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "Background process failed to start (pid=$pid)."
    exit 1
  fi
done

echo "Starting VideoMemory web app at :${PORT:-5050}..."
exec uv run flask_app/app.py
