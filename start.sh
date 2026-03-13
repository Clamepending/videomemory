#!/usr/bin/env bash
# Start MediaMTX, configure networking, and launch VideoMemory.
# On first run, installs any missing dependencies and guides through setup.
# Usage: ./start.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

bold()  { printf "\033[1m%s\033[0m" "$*"; }
green() { printf "\033[1;32m%s\033[0m" "$*"; }

# ---------------------------------------------------------------------------
# 0. uv – Python package manager
# ---------------------------------------------------------------------------
if ! command -v uv &>/dev/null; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  echo "$(green '✓') uv installed"
fi

# ---------------------------------------------------------------------------
# 1. MediaMTX – RTMP/RTSP relay (auto-downloads if missing)
# ---------------------------------------------------------------------------
source "$REPO_ROOT/scripts/start_mediamtx.sh"

# ---------------------------------------------------------------------------
# 2. Tailscale – enable remote streaming over cellular (guides setup if missing)
# ---------------------------------------------------------------------------
source "$REPO_ROOT/scripts/start_tailscale.sh"

# ---------------------------------------------------------------------------
# 3. Local vLLM – optional local vision model (instead of cloud APIs)
# ---------------------------------------------------------------------------
source "$REPO_ROOT/scripts/start_vllm.sh"

# ---------------------------------------------------------------------------
# 4. VideoMemory – start the Flask application
# ---------------------------------------------------------------------------
echo ""
echo "$(bold 'Starting VideoMemory...')"
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo "  Local:     $(bold "http://${LOCAL_IP}:5050")"
if [[ -n "${RTMP_SERVER_HOST:-}" ]]; then
  echo "  Tailscale: $(bold "http://${RTMP_SERVER_HOST}:5050")"
fi
echo ""

exec uv run flask_app/app.py
