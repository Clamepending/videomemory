#!/usr/bin/env bash
# Run MediaMTX with project config. Requires mediamtx in PATH or current dir.
set -e
cd "$(dirname "$0")"
if command -v mediamtx &>/dev/null; then
  exec mediamtx mediamtx.yml
elif [[ -x ./mediamtx ]]; then
  exec ./mediamtx mediamtx.yml
else
  echo "MediaMTX not found. Install: brew install mediamtx (or download from https://github.com/bluenviron/mediamtx/releases)"
  exit 1
fi
