#!/usr/bin/env sh

set -eu

log() {
  printf '[videomemory-relaunch] %s\n' "$*"
}

fail() {
  printf '[videomemory-relaunch] ERROR: %s\n' "$*" >&2
  exit 1
}

REPO_URL="${VIDEOMEMORY_REPO_URL:-https://github.com/Clamepending/videomemory.git}"
REPO_REF="${VIDEOMEMORY_REPO_REF:-main}"
REPO_DIR="${VIDEOMEMORY_REPO_DIR:-$HOME/videomemory}"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
VIDEOMEMORY_BASE="${VIDEOMEMORY_BASE:-http://127.0.0.1:5050}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_DIR="${VIDEOMEMORY_STATE_DIR:-$STATE_HOME/videomemory}"
LOG_FILE="$STATE_DIR/server.log"
PID_FILE="$STATE_DIR/server.pid"
SKIP_KEYS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --repo-ref)
      REPO_REF="$2"
      shift 2
      ;;
    --repo-dir)
      REPO_DIR="$2"
      shift 2
      ;;
    --openclaw-home)
      OPENCLAW_HOME="$2"
      shift 2
      ;;
    --videomemory-base)
      VIDEOMEMORY_BASE="$2"
      shift 2
      ;;
    --skip-keys)
      SKIP_KEYS=1
      shift 1
      ;;
    --help|-h)
      cat <<'EOF'
Usage: relaunch-videomemory.sh [options]

Options:
  --repo-url URL          VideoMemory git URL
  --repo-ref REF          Git branch/tag to use
  --repo-dir DIR          Checkout location
  --openclaw-home DIR     OpenClaw home directory
  --videomemory-base URL  Host URL where VideoMemory should be reachable
  --skip-keys             Do not copy model API keys into VideoMemory after restart
EOF
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

VENV_PYTHON="$REPO_DIR/.venv/bin/python"
REPO_UPDATED=0
REPO_COMMIT=""

find_bin() {
  for candidate in "$@"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

GIT_BIN="$(find_bin git || true)"
CURL_BIN="$(find_bin curl || true)"
PYTHON_BIN="$(find_bin python3 || true)"
UV_BIN="$(find_bin "$HOME/.local/bin/uv" /home/linuxbrew/.linuxbrew/bin/uv uv || true)"
TAILSCALE_BIN="$(find_bin tailscale || true)"

[ -n "$CURL_BIN" ] || fail "curl is required"
[ -n "$GIT_BIN" ] || fail "git is required"
[ -n "$UV_BIN" ] || [ -n "$PYTHON_BIN" ] || fail "uv or python3 is required to launch VideoMemory without Docker"

ensure_repo() {
  if [ ! -d "$REPO_DIR/.git" ]; then
    log "Cloning VideoMemory from $REPO_URL into $REPO_DIR"
    mkdir -p "$(dirname "$REPO_DIR")"
    "$GIT_BIN" clone --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR" >/dev/null
    REPO_UPDATED=1
    REPO_COMMIT="$("$GIT_BIN" -C "$REPO_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
    return 0
  fi

  log "Using existing repo at $REPO_DIR"
  before_commit="$("$GIT_BIN" -C "$REPO_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"

  if ! "$GIT_BIN" -C "$REPO_DIR" diff --quiet --ignore-submodules HEAD -- >/dev/null 2>&1; then
    log "Repo has local changes; skipping automatic upgrade and keeping current checkout."
    REPO_COMMIT="$before_commit"
    return 0
  fi

  if "$GIT_BIN" -C "$REPO_DIR" fetch origin "$REPO_REF" >/dev/null 2>&1 \
    && "$GIT_BIN" -C "$REPO_DIR" merge --ff-only FETCH_HEAD >/dev/null 2>&1; then
    :
  else
    log "Repo update skipped (non-fast-forward or fetch failure). Continuing with existing checkout."
  fi

  after_commit="$("$GIT_BIN" -C "$REPO_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
  REPO_COMMIT="$after_commit"
  if [ -n "$before_commit" ] && [ -n "$after_commit" ] && [ "$before_commit" != "$after_commit" ]; then
    REPO_UPDATED=1
  fi
}

prepare_runtime() {
  mkdir -p "$STATE_DIR"

  if [ -n "$UV_BIN" ]; then
    log "Preparing Python environment with uv"
    (
      cd "$REPO_DIR"
      "$UV_BIN" sync >>"$LOG_FILE" 2>&1
    ) || fail "uv sync failed; check $LOG_FILE"
    return 0
  fi

  [ -n "$PYTHON_BIN" ] || fail "python3 is required when uv is not installed"

  if [ ! -x "$VENV_PYTHON" ]; then
    log "Creating Python virtual environment at $REPO_DIR/.venv"
    "$PYTHON_BIN" -m venv "$REPO_DIR/.venv" >>"$LOG_FILE" 2>&1 || fail "python3 -m venv failed; check $LOG_FILE"
  fi

  if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    log "Bootstrapping pip inside $REPO_DIR/.venv"
    "$VENV_PYTHON" -m ensurepip --upgrade >>"$LOG_FILE" 2>&1 || fail "ensurepip failed; check $LOG_FILE"
  fi

  log "Installing VideoMemory dependencies into $REPO_DIR/.venv"
  "$VENV_PYTHON" -m pip install --upgrade pip >>"$LOG_FILE" 2>&1 || fail "pip upgrade failed; check $LOG_FILE"
  "$VENV_PYTHON" -m pip install -e "$REPO_DIR" >>"$LOG_FILE" 2>&1 || fail "dependency install failed; check $LOG_FILE"
}

pid_is_running() {
  pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1
}

healthcheck() {
  "$CURL_BIN" -fsS "$VIDEOMEMORY_BASE/api/health" >/dev/null 2>&1
}

stop_local_videomemory() {
  if [ ! -f "$PID_FILE" ]; then
    if healthcheck; then
      fail "VideoMemory is running at $VIDEOMEMORY_BASE but is not managed by $PID_FILE. Stop that service manually or rerun the bootstrap path first."
    fi
    return 0
  fi

  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if ! pid_is_running "$existing_pid"; then
    rm -f "$PID_FILE"
    return 0
  fi

  log "Stopping VideoMemory process $existing_pid"
  kill "$existing_pid" >/dev/null 2>&1 || true

  i=0
  while [ "$i" -lt 30 ]; do
    if ! pid_is_running "$existing_pid"; then
      rm -f "$PID_FILE"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done

  log "Process $existing_pid did not exit after SIGTERM; sending SIGKILL"
  kill -9 "$existing_pid" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
}

start_local_videomemory() {
  mkdir -p "$STATE_DIR"

  log "Launching VideoMemory directly on the host"
  if [ -n "$UV_BIN" ]; then
    (
      cd "$REPO_DIR"
      nohup "$UV_BIN" run flask_app/app.py >>"$LOG_FILE" 2>&1 &
      echo $! >"$PID_FILE"
    )
  else
    (
      cd "$REPO_DIR"
      nohup "$VENV_PYTHON" flask_app/app.py >>"$LOG_FILE" 2>&1 &
      echo $! >"$PID_FILE"
    )
  fi
}

wait_for_health() {
  log "Waiting for VideoMemory health at $VIDEOMEMORY_BASE"
  i=0
  while [ "$i" -lt 60 ]; do
    if healthcheck; then
      log "VideoMemory is healthy"
      return 0
    fi
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && ! pid_is_running "$pid"; then
      fail "VideoMemory exited before becoming healthy; check $LOG_FILE"
    fi
    i=$((i + 1))
    sleep 2
  done

  fail "VideoMemory did not become healthy at $VIDEOMEMORY_BASE; check $LOG_FILE"
}

sync_model_keys() {
  if [ "$SKIP_KEYS" -eq 1 ]; then
    log "Skipping model key sync"
    return 0
  fi

  if [ -n "${GEMINI_API_KEY:-}" ] && [ -z "${GOOGLE_API_KEY:-}" ]; then
    GOOGLE_API_KEY="$GEMINI_API_KEY"
    export GOOGLE_API_KEY
  fi

  for key in GOOGLE_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY ANTHROPIC_API_KEY; do
    value="$(printenv "$key" || true)"
    if [ -z "$value" ]; then
      continue
    fi
    log "Copying $key into VideoMemory settings"
    "$CURL_BIN" -fsS -X PUT "$VIDEOMEMORY_BASE/api/settings/$key" \
      -H 'Content-Type: application/json' \
      -d "{\"value\":\"$value\"}" >/dev/null || log "Warning: failed to copy $key"
  done

  selected_model="${VIDEO_INGESTOR_MODEL:-}"
  if [ -z "$selected_model" ]; then
    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
      selected_model="claude-sonnet-4-6"
    elif [ -n "${OPENAI_API_KEY:-}" ]; then
      selected_model="gpt-4o-mini"
    elif [ -n "${GOOGLE_API_KEY:-}" ]; then
      selected_model="gemini-2.5-flash"
    elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
      selected_model="qwen3-vl-8b"
    fi
  fi

  if [ -n "$selected_model" ]; then
    log "Setting VIDEO_INGESTOR_MODEL to $selected_model"
    "$CURL_BIN" -fsS -X PUT "$VIDEOMEMORY_BASE/api/settings/VIDEO_INGESTOR_MODEL" \
      -H 'Content-Type: application/json' \
      -d "{\"value\":\"$selected_model\"}" >/dev/null || log "Warning: failed to set VIDEO_INGESTOR_MODEL"
  fi
}

read_openclaw_webhook_config() {
  CONFIG_PATH="$OPENCLAW_HOME/openclaw.json"
  [ -f "$CONFIG_PATH" ] || return 0

  if [ -n "$PYTHON_BIN" ]; then
    OPENCLAW_CONFIG_PATH="$CONFIG_PATH" "$PYTHON_BIN" <<'EOF'
import json
import os
from pathlib import Path

try:
    config = json.loads(Path(os.environ["OPENCLAW_CONFIG_PATH"]).read_text())
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        gateway = {}
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    mappings = hooks.get("mappings")
    if not isinstance(mappings, list):
        mappings = []

    mapping = None
    for entry in mappings:
        if isinstance(entry, dict) and entry.get("id") == "videomemory-alert":
            mapping = entry
            break
    if mapping is None:
        for entry in mappings:
            if isinstance(entry, dict) and isinstance(entry.get("match"), dict) and entry["match"].get("path"):
                mapping = entry
                break

    try:
        port = int(gateway.get("port") or 18789)
    except (TypeError, ValueError):
        port = 18789

    hooks_path = str(hooks.get("path") or "/hooks").strip() or "/hooks"
    mapping_path = "videomemory-alert"
    if isinstance(mapping, dict):
        match = mapping.get("match")
        if isinstance(match, dict) and str(match.get("path") or "").strip():
            mapping_path = str(match.get("path")).strip()

    if not hooks_path.startswith("/"):
        hooks_path = "/" + hooks_path
    mapping_path = mapping_path.lstrip("/")

    url = f"http://127.0.0.1:{port}{hooks_path}/{mapping_path}"
    token = str(hooks.get("token") or "").strip()
    print(url)
    print(token)
    print("openclaw", end="")
except Exception:
    pass
EOF
    return 0
  fi
}

sync_openclaw_webhook_settings() {
  CONFIG_PATH="$OPENCLAW_HOME/openclaw.json"
  if [ ! -f "$CONFIG_PATH" ]; then
    log "OpenClaw config not found at $CONFIG_PATH; skipping webhook sync"
    return 0
  fi

  webhook_info="$(read_openclaw_webhook_config || true)"
  webhook_url="$(printf '%s\n' "$webhook_info" | sed -n '1p')"
  webhook_token="$(printf '%s\n' "$webhook_info" | sed -n '2p')"
  webhook_bot_id="$(printf '%s\n' "$webhook_info" | sed -n '3p')"

  if [ -z "$webhook_url" ]; then
    log "Warning: could not derive the OpenClaw webhook URL from $CONFIG_PATH"
    return 0
  fi

  log "Copying OpenClaw webhook settings into VideoMemory"
  "$CURL_BIN" -fsS -X PUT "$VIDEOMEMORY_BASE/api/settings/VIDEOMEMORY_SELF_BASE_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"value\":\"$VIDEOMEMORY_BASE\"}" >/dev/null || log "Warning: failed to set VIDEOMEMORY_SELF_BASE_URL"

  "$CURL_BIN" -fsS -X PUT "$VIDEOMEMORY_BASE/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"value\":\"$webhook_url\"}" >/dev/null || log "Warning: failed to set VIDEOMEMORY_OPENCLAW_WEBHOOK_URL"

  if [ -n "$webhook_token" ]; then
    "$CURL_BIN" -fsS -X PUT "$VIDEOMEMORY_BASE/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN" \
      -H 'Content-Type: application/json' \
      -d "{\"value\":\"$webhook_token\"}" >/dev/null || log "Warning: failed to set VIDEOMEMORY_OPENCLAW_WEBHOOK_TOKEN"
  fi

  if [ -n "$webhook_bot_id" ]; then
    "$CURL_BIN" -fsS -X PUT "$VIDEOMEMORY_BASE/api/settings/VIDEOMEMORY_OPENCLAW_BOT_ID" \
      -H 'Content-Type: application/json' \
      -d "{\"value\":\"$webhook_bot_id\"}" >/dev/null || log "Warning: failed to set VIDEOMEMORY_OPENCLAW_BOT_ID"
  fi
}

pick_user_facing_ui_url() {
  if [ -n "$TAILSCALE_BIN" ]; then
    tailscale_ip="$("$TAILSCALE_BIN" ip -4 2>/dev/null | sed -n '1p' || true)"
    if [ -n "$tailscale_ip" ]; then
      printf 'http://%s:5050/devices\n' "$tailscale_ip"
      return 0
    fi
  fi

  printf '%s/devices\n' "$VIDEOMEMORY_BASE"
}

ensure_repo
prepare_runtime
stop_local_videomemory
start_local_videomemory
wait_for_health
sync_model_keys
sync_openclaw_webhook_settings

USER_FACING_UI_URL="$(pick_user_facing_ui_url)"

log "Relaunch complete"
if [ "$REPO_UPDATED" -eq 1 ]; then
  log "Upgraded repo to latest $REPO_REF"
else
  log "Repo already up to date for $REPO_REF"
fi
if [ -n "$REPO_COMMIT" ]; then
  log "Running repo commit: $REPO_COMMIT"
fi
log "User-facing VideoMemory UI: $USER_FACING_UI_URL"
log "VideoMemory log: $LOG_FILE"
log "Reply to the user with this VideoMemory UI link: $USER_FACING_UI_URL"
