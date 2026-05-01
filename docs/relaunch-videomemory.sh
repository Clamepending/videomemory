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
DRY_RUN=0

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
    --dry-run|--explain)
      DRY_RUN=1
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
  --dry-run, --explain    Print the relaunch plan without making changes
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
LSOF_BIN="$(find_bin lsof || true)"
SS_BIN="$(find_bin ss || true)"

[ -n "$CURL_BIN" ] || fail "curl is required"
[ -n "$GIT_BIN" ] || fail "git is required"
[ -n "$UV_BIN" ] || [ -n "$PYTHON_BIN" ] || fail "uv or python3 is required to launch VideoMemory without Docker"

ensure_repo() {
  before_commit=""
  if [ -d "$REPO_DIR/.git" ]; then
    log "Using existing repo at $REPO_DIR"
    before_commit="$("$GIT_BIN" -C "$REPO_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
    if ! "$GIT_BIN" -C "$REPO_DIR" diff --quiet --ignore-submodules HEAD -- >/dev/null 2>&1; then
      log "Repo has local changes; skipping automatic upgrade and keeping current checkout."
      REPO_COMMIT="$before_commit"
      return 0
    fi
  else
    log "Cloning VideoMemory source into $REPO_DIR"
    mkdir -p "$(dirname "$REPO_DIR")"
    "$GIT_BIN" clone --filter=blob:none --no-checkout "$REPO_URL" "$REPO_DIR" >/dev/null
    REPO_UPDATED=1
  fi

  "$GIT_BIN" -C "$REPO_DIR" fetch --depth 1 origin "$REPO_REF" >/dev/null
  "$GIT_BIN" -C "$REPO_DIR" sparse-checkout init --no-cone >/dev/null
  "$GIT_BIN" -C "$REPO_DIR" sparse-checkout set \
    /pyproject.toml \
    /uv.lock \
    /flask_app/ \
    /videomemory/ \
    /docs/update-manifest.json \
    /docs/openclaw-skill.md \
    /docs/openclaw-videomemory-task-helper.mjs \
    /scripts/openclaw_send_current_camera_image.sh \
    /deploy/openclaw-real-home/hooks/transforms/videomemory-alert.mjs >/dev/null
  "$GIT_BIN" -C "$REPO_DIR" checkout --detach FETCH_HEAD >/dev/null

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

port_from_base_url() {
  hostport="${1#*://}"
  hostport="${hostport%%/*}"
  case "$hostport" in
    *:*)
      printf '%s\n' "${hostport##*:}"
      ;;
    *)
      case "$1" in
        https://*)
          printf '443\n'
          ;;
        *)
          printf '80\n'
          ;;
      esac
      ;;
  esac
}

listener_pid() {
  port="$(port_from_base_url "$VIDEOMEMORY_BASE")"
  if [ -n "$LSOF_BIN" ]; then
    "$LSOF_BIN" -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sed -n '1p'
    return 0
  fi
  if [ -n "$SS_BIN" ]; then
    "$SS_BIN" -ltnp 2>/dev/null | awk -v port=":$port" '
      $4 ~ port"$" {
        if (match($0, /pid=([0-9]+)/)) {
          value = substr($0, RSTART, RLENGTH)
          sub(/^pid=/, "", value)
          print value
          exit
        }
      }
    '
  fi
}

pid_looks_like_videomemory() {
  pid="${1:-}"
  [ -n "$pid" ] || return 1
  args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case "$args" in
    *"flask_app/app.py"*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

stop_pid_gracefully() {
  pid="${1:-}"
  label="${2:-process}"
  [ -n "$pid" ] || return 0
  if ! pid_is_running "$pid"; then
    return 0
  fi

  log "Stopping $label $pid"
  kill "$pid" >/dev/null 2>&1 || true

  i=0
  while [ "$i" -lt 30 ]; do
    if ! pid_is_running "$pid"; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done

  log "$label $pid did not exit after SIGTERM; sending SIGKILL"
  kill -9 "$pid" >/dev/null 2>&1 || true
}

sync_pid_file_to_listener() {
  pid="$(listener_pid || true)"
  if [ -n "$pid" ] && pid_is_running "$pid" && pid_looks_like_videomemory "$pid"; then
    printf '%s\n' "$pid" >"$PID_FILE"
    return 0
  fi
  return 1
}

healthcheck() {
  "$CURL_BIN" -fsS "$VIDEOMEMORY_BASE/api/health" >/dev/null 2>&1
}

stop_local_videomemory() {
  existing_pid=""
  if [ -f "$PID_FILE" ]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  fi

  if [ -n "$existing_pid" ] && pid_is_running "$existing_pid"; then
    stop_pid_gracefully "$existing_pid" "VideoMemory process"
  else
    rm -f "$PID_FILE"
  fi

  existing_listener_pid="$(listener_pid || true)"
  if [ -n "$existing_listener_pid" ] && [ "$existing_listener_pid" != "$existing_pid" ] && pid_looks_like_videomemory "$existing_listener_pid"; then
    stop_pid_gracefully "$existing_listener_pid" "stale VideoMemory listener"
  fi

  rm -f "$PID_FILE"

  if healthcheck; then
    fail "VideoMemory is still reachable at $VIDEOMEMORY_BASE after stop; another process is holding the port."
  fi
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
      sync_pid_file_to_listener || true
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

copy_if_exists() {
  src="$1"
  dest="$2"
  [ -f "$src" ] || fail "Missing file: $src"
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
}

copy_executable_if_exists() {
  src="$1"
  dest="$2"
  copy_if_exists "$src" "$dest"
  chmod 755 "$dest"
}

install_openclaw_files() {
  copy_if_exists \
    "$REPO_DIR/docs/openclaw-videomemory-task-helper.mjs" \
    "$OPENCLAW_HOME/hooks/bin/videomemory-task-helper.mjs"
  copy_if_exists \
    "$REPO_DIR/deploy/openclaw-real-home/hooks/transforms/videomemory-alert.mjs" \
    "$OPENCLAW_HOME/hooks/transforms/videomemory-alert.mjs"
  copy_if_exists \
    "$REPO_DIR/docs/openclaw-skill.md" \
    "$OPENCLAW_HOME/workspace/skills/videomemory/SKILL.md"
  copy_executable_if_exists \
    "$REPO_DIR/scripts/openclaw_send_current_camera_image.sh" \
    "$OPENCLAW_HOME/workspace/bin/openclaw_send_current_camera_image.sh"
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

explain_plan() {
  log "VideoMemory relaunch plan"
  log "Repo URL: $REPO_URL"
  log "Repo ref: $REPO_REF"
  log "Repo dir: $REPO_DIR"
  log "OpenClaw home: $OPENCLAW_HOME"
  log "VideoMemory base: $VIDEOMEMORY_BASE"
  log "State dir: $STATE_DIR"
  log "Will clone/update the repo if needed, prepare the local Python environment, restart VideoMemory, and wait for health"
  log "Will sync OpenClaw webhook settings into VideoMemory when OpenClaw config is present"
  if [ "$SKIP_KEYS" -eq 1 ]; then
    log "Will not copy model provider API keys into VideoMemory after restart"
  else
    log "Will copy model provider API keys from the current environment into VideoMemory settings when present"
  fi
  log "No changes were made because --dry-run/--explain was set"
}

if [ "$DRY_RUN" -eq 1 ]; then
  explain_plan
  exit 0
fi

ensure_repo
prepare_runtime
stop_local_videomemory
start_local_videomemory
wait_for_health
install_openclaw_files
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
log "OpenClaw camera image helper: $OPENCLAW_HOME/workspace/bin/openclaw_send_current_camera_image.sh"
log "VideoMemory log: $LOG_FILE"
log "Reply to the user with this VideoMemory UI link: $USER_FACING_UI_URL"
log "If OpenClaw was already chatting before this relaunch, send /new once so the next session loads the refreshed VideoMemory image helper guidance."
