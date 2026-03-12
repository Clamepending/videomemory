#!/usr/bin/env bash
# Start MediaMTX (RTMP/RTSP relay) and VideoMemory in one command.
# Usage: ./start.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

MEDIAMTX_PID=""
MEDIAMTX_CFG="$REPO_ROOT/rtmp-server/mediamtx.yml"

cleanup() { [[ -n "$MEDIAMTX_PID" ]] && kill "$MEDIAMTX_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Reuse an already-running MediaMTX that was started with our config.
if pid=$(pgrep -f "mediamtx $MEDIAMTX_CFG" | head -1) && kill -0 "$pid" 2>/dev/null; then
  echo "MediaMTX already running (PID $pid), reusing."
else
  # Resolve the binary.
  if command -v mediamtx &>/dev/null; then
    MTX=mediamtx
  elif [[ -x "$REPO_ROOT/rtmp-server/mediamtx" ]]; then
    MTX="$REPO_ROOT/rtmp-server/mediamtx"
  else
    echo "MediaMTX not found. Install: brew install mediamtx"
    exit 1
  fi

  "$MTX" "$MEDIAMTX_CFG" &
  MEDIAMTX_PID=$!
  sleep 1
  kill -0 "$MEDIAMTX_PID" 2>/dev/null || { echo "MediaMTX failed to start."; exit 1; }
  echo "MediaMTX started (PID $MEDIAMTX_PID). RTMP :1935, RTSP :8554"
fi

# Use Tailscale IP for RTMP URLs when available (enables phone-on-cellular streaming).
if [[ -z "$RTMP_SERVER_HOST" ]]; then
  TS_IP=$(tailscale ip -4 2>/dev/null || true)
  if [[ -n "$TS_IP" ]]; then
    export RTMP_SERVER_HOST="$TS_IP"
    echo "Tailscale connected: RTMP_SERVER_HOST=$TS_IP"
  else
    echo "Tailscale not active. To stream from outside your local network,"
    echo "install Tailscale: https://tailscale.com/download"
  fi
fi

exec uv run flask_app/app.py
