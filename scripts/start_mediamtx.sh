#!/usr/bin/env bash
# Start MediaMTX (RTMP/RTSP relay) or reuse an already-running instance.
# Auto-downloads the binary on first run if not found.

set -e
: "${REPO_ROOT:="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"
MEDIAMTX_CFG="$REPO_ROOT/rtmp-server/mediamtx.yml"
MEDIAMTX_LOCAL="$REPO_ROOT/rtmp-server/mediamtx"
MEDIAMTX_VERSION="1.16.3"

# Check for an existing instance started with our config
if pid=$(pgrep -f "mediamtx $MEDIAMTX_CFG" | head -1) && kill -0 "$pid" 2>/dev/null; then
  echo "MediaMTX already running (PID $pid), reusing."
  export MEDIAMTX_PID=""
  return 0 2>/dev/null || exit 0
fi

# Find the mediamtx binary (PATH first, then local copy, then auto-download)
if command -v mediamtx &>/dev/null; then
  MTX=mediamtx
elif [[ -x "$MEDIAMTX_LOCAL" ]]; then
  MTX="$MEDIAMTX_LOCAL"
else
  echo "MediaMTX not found — downloading v${MEDIAMTX_VERSION}..."
  case "$(uname -s)" in
    Linux)  OS="linux" ;;
    Darwin) OS="darwin" ;;
    *)      echo "Unsupported OS: $(uname -s)"; exit 1 ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64)   ARCH="amd64" ;;
    aarch64|arm64)   ARCH="arm64" ;;
    armv7l|armhf)    ARCH="armv7" ;;
    *)               echo "Unsupported arch: $(uname -m)"; exit 1 ;;
  esac
  URL="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_${OS}_${ARCH}.tar.gz"
  curl -fsSL "$URL" | tar -xz -C "$REPO_ROOT/rtmp-server" mediamtx
  chmod +x "$MEDIAMTX_LOCAL"
  echo "MediaMTX downloaded to $MEDIAMTX_LOCAL"
  MTX="$MEDIAMTX_LOCAL"
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
