#!/usr/bin/env bash
# Start MediaMTX (RTMP/RTSP relay) or reuse an already-running instance.
# Registers a trap to kill MediaMTX when the parent script exits.

set -e
: "${REPO_ROOT:="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"
MEDIAMTX_CFG="$REPO_ROOT/rtmp-server/mediamtx.yml"

# Check for an existing instance started with our config
if pid=$(pgrep -f "mediamtx $MEDIAMTX_CFG" | head -1) && kill -0 "$pid" 2>/dev/null; then
  echo "MediaMTX already running (PID $pid), reusing."
  export MEDIAMTX_PID=""
  return 0 2>/dev/null || exit 0
fi

# Find the mediamtx binary (PATH first, then local copy)
if command -v mediamtx &>/dev/null; then
  MTX=mediamtx
elif [[ -x "$REPO_ROOT/rtmp-server/mediamtx" ]]; then
  MTX="$REPO_ROOT/rtmp-server/mediamtx"
else
  echo "MediaMTX not found. Install: brew install mediamtx"
  exit 1
fi

# Launch in the background and verify it started
"$MTX" "$MEDIAMTX_CFG" &
export MEDIAMTX_PID=$!
sleep 1
kill -0 "$MEDIAMTX_PID" 2>/dev/null || { echo "MediaMTX failed to start."; exit 1; }
echo "MediaMTX started (PID $MEDIAMTX_PID). RTMP :1935, RTSP :8554"

# Kill MediaMTX when the parent script exits
cleanup() { [[ -n "$MEDIAMTX_PID" ]] && kill "$MEDIAMTX_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
