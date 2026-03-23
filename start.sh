#!/usr/bin/env bash
# Start the VideoMemory web app.
# Usage: ./start.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

exec uv run flask_app/app.py
