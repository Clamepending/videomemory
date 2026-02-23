#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MEDIAMTX_PID=""
cleanup() {
  if [[ -n "$MEDIAMTX_PID" ]] && kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
    echo "Stopping MediaMTX (PID $MEDIAMTX_PID)..."
    kill "$MEDIAMTX_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting MediaMTX (RTMP :1935, RTSP :8554)..."
/usr/local/bin/mediamtx "$REPO_ROOT/rtmp-server/mediamtx.yml" &
MEDIAMTX_PID=$!

sleep 1
if ! kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
  echo "MediaMTX failed to start."
  exit 1
fi

echo "Starting VideoMemory web app at :5050..."
exec uv run flask_app/app.py
