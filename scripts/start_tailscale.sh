#!/usr/bin/env bash
# Detect Tailscale and export RTMP_SERVER_HOST so phones can stream over cellular.

set -e

# Skip if the host is already set explicitly
if [[ -n "$RTMP_SERVER_HOST" ]]; then
  return 0 2>/dev/null || exit 0
fi

TS_IP=$(tailscale ip -4 2>/dev/null || true)
if [[ -n "$TS_IP" ]]; then
  export RTMP_SERVER_HOST="$TS_IP"
  echo "Tailscale connected: RTMP_SERVER_HOST=$TS_IP"
else
  echo "Tailscale not active. To stream from outside your local network,"
  echo "install Tailscale: https://tailscale.com/download"
fi
