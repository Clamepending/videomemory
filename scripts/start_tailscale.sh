#!/usr/bin/env bash
# Detect Tailscale, guide through installation if missing, and export
# RTMP_SERVER_HOST so phones can stream over cellular.

set -e

# Skip if the host is already set explicitly
if [[ -n "$RTMP_SERVER_HOST" ]]; then
  return 0 2>/dev/null || exit 0
fi

bold()  { printf "\033[1m%s\033[0m" "$*"; }
green() { printf "\033[1;32m%s\033[0m" "$*"; }
dim()   { printf "\033[2m%s\033[0m" "$*"; }

# --- Check if Tailscale is installed ---
if ! command -v tailscale &>/dev/null; then
  echo ""
  echo "$(bold 'Tailscale is not installed.')"
  echo "Tailscale lets you stream video from your phone over cellular."
  echo ""
  read -rp "Install Tailscale now? [Y/n] " install_ts
  if [[ "${install_ts,,}" == "n" ]]; then
    echo "$(dim 'Skipping Tailscale — video streaming will only work on local network.')"
    return 0 2>/dev/null || exit 0
  fi

  echo "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh

  if ! command -v tailscale &>/dev/null; then
    echo "Tailscale install failed. You can install manually: https://tailscale.com/download"
    return 0 2>/dev/null || exit 0
  fi
  echo "$(green '✓') Tailscale installed"
fi

# --- Check if Tailscale is connected ---
TS_IP=$(tailscale ip -4 2>/dev/null || true)

if [[ -z "$TS_IP" ]]; then
  TS_STATUS=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('BackendState',''))" 2>/dev/null || echo "unknown")

  if [[ "$TS_STATUS" == "NeedsLogin" || "$TS_STATUS" == "unknown" || "$TS_STATUS" == "Stopped" ]]; then
    # If tailscaled daemon isn't running, try to start it
    if [[ "$TS_STATUS" == "unknown" ]]; then
      echo ""
      echo "Starting tailscaled..."
      if sudo tailscaled 2>/dev/null & sleep 2 && sudo tailscale status &>/dev/null; then
        true
      else
        # Kernel TUN unavailable (containers, restricted VMs) — fall back to userspace
        sudo pkill tailscaled 2>/dev/null || true
        sleep 1
        echo "$(dim 'Using userspace networking (restricted environment detected)')"
        sudo tailscaled --tun=userspace-networking \
          --state=/var/lib/tailscale/tailscaled.state \
          --socket=/run/tailscale/tailscaled.sock &>/dev/null &
        sleep 2
      fi
    fi

    echo ""
    echo "$(bold 'Tailscale needs to be connected to your account.')"
    echo ""

    if [[ $EUID -eq 0 ]] || sudo -n true 2>/dev/null; then
      echo "Starting Tailscale login..."
      sudo tailscale up
    else
      echo "Run this to connect:"
      echo "  $(bold 'sudo tailscale up')"
      echo ""
      read -rp "Press Enter after you've connected Tailscale (or 's' to skip): " ts_wait
      if [[ "${ts_wait,,}" == "s" ]]; then
        echo "$(dim 'Skipping Tailscale — video streaming will only work on local network.')"
        return 0 2>/dev/null || exit 0
      fi
    fi

    TS_IP=$(tailscale ip -4 2>/dev/null || true)
  fi
fi

if [[ -n "$TS_IP" ]]; then
  export RTMP_SERVER_HOST="$TS_IP"
  echo "$(green '✓') Tailscale connected: RTMP_SERVER_HOST=$TS_IP"
else
  echo "$(dim 'Tailscale not connected. Video streaming will only work on local network.')"
  echo "$(dim 'Run: sudo tailscale up')"
fi
