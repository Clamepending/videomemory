#!/usr/bin/env bash
# Start MediaMTX, configure networking, and launch VideoMemory.
# Usage: ./start.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 1. MediaMTX – RTMP/RTSP relay
# ---------------------------------------------------------------------------
source "$REPO_ROOT/scripts/start_mediamtx.sh"

# ---------------------------------------------------------------------------
# 2. Tailscale – enable remote streaming over cellular
# ---------------------------------------------------------------------------
source "$REPO_ROOT/scripts/start_tailscale.sh"

# ---------------------------------------------------------------------------
# 3. VideoMemory – start the Flask application
# ---------------------------------------------------------------------------
exec uv run flask_app/app.py
