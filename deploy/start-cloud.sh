#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

exec /app/.venv/bin/python /app/flask_app/app.py
