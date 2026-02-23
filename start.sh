#!/usr/bin/env bash
# Start MediaMTX (RTMP/RTSP relay) and VideoMemory in one command for local testing.
# Usage: ./start.sh
# Then open http://localhost:5050, go to Devices, click "Create RTMP camera", paste the URL in the Android app.

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

MEDIAMTX_PID=""
cleanup() {
  if [[ -n "$MEDIAMTX_PID" ]] && kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
    echo "Stopping MediaMTX (PID $MEDIAMTX_PID)..."
    kill "$MEDIAMTX_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Start MediaMTX in background (RTMP :1935, RTSP :8554)
if command -v mediamtx &>/dev/null; then
  mediamtx "$REPO_ROOT/rtmp-server/mediamtx.yml" &
  MEDIAMTX_PID=$!
  echo "MediaMTX started (PID $MEDIAMTX_PID). RTMP :1935, RTSP :8554"
elif [[ -x "$REPO_ROOT/rtmp-server/mediamtx" ]]; then
  "$REPO_ROOT/rtmp-server/mediamtx" "$REPO_ROOT/rtmp-server/mediamtx.yml" &
  MEDIAMTX_PID=$!
  echo "MediaMTX started (PID $MEDIAMTX_PID). RTMP :1935, RTSP :8554"
else
  echo "MediaMTX not found. Install: brew install mediamtx (or download from https://github.com/bluenviron/mediamtx/releases)"
  exit 1
fi

sleep 1
if ! kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
  echo "MediaMTX failed to start."
  exit 1
fi

# Run VideoMemory (Flask)
echo "Starting VideoMemory at http://localhost:5050"
exec uv run flask_app/app.py
