#!/usr/bin/env bash
# Start MediaMTX (RTMP/RTSP relay) and VideoMemory in one command for local testing.
# Usage: ./start.sh
# Then open http://localhost:${PORT:-5050} (or https if SSL_ADHOC=1),
# go to Devices, click "Create RTMP camera", paste the URL in the Android app.

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

MEDIAMTX_PID=""
MEDIAMTX_CONFIG="$REPO_ROOT/rtmp-server/mediamtx.yml"
cleanup() {
  if [[ -n "$MEDIAMTX_PID" ]] && kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
    echo "Stopping MediaMTX (PID $MEDIAMTX_PID)..."
    kill "$MEDIAMTX_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Reuse existing MediaMTX started with this repo config, if present.
EXISTING_MEDIAMTX_PIDS="$(pgrep -f "mediamtx $MEDIAMTX_CONFIG" || true)"
EXISTING_MEDIAMTX_PID="${EXISTING_MEDIAMTX_PIDS%%$'\n'*}"
if [[ -n "$EXISTING_MEDIAMTX_PID" ]] && kill -0 "$EXISTING_MEDIAMTX_PID" 2>/dev/null; then
  echo "MediaMTX already running (PID $EXISTING_MEDIAMTX_PID), reusing it."
else
  # Start MediaMTX in background (RTMP :1935, RTSP :8554)
  if command -v mediamtx &>/dev/null; then
    mediamtx "$MEDIAMTX_CONFIG" &
    MEDIAMTX_PID=$!
    echo "MediaMTX started (PID $MEDIAMTX_PID). RTMP :1935, RTSP :8554"
  elif [[ -x "$REPO_ROOT/rtmp-server/mediamtx" ]]; then
    "$REPO_ROOT/rtmp-server/mediamtx" "$MEDIAMTX_CONFIG" &
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
fi

# Run VideoMemory (Flask)
PORT="${PORT:-5050}"
SSL_ADHOC="${SSL_ADHOC:-0}"
PROTO="http"
if [[ "$SSL_ADHOC" == "1" ]]; then
  PROTO="https"
fi
echo "Starting VideoMemory at ${PROTO}://localhost:${PORT}"
exec uv run flask_app/app.py
