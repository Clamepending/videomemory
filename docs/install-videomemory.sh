#!/usr/bin/env sh

set -eu

log() {
  printf '[videomemory-install] %s\n' "$*"
}

fail() {
  printf '[videomemory-install] ERROR: %s\n' "$*" >&2
  exit 1
}

REPO_URL="${VIDEOMEMORY_REPO_URL:-https://github.com/Clamepending/videomemory.git}"
REPO_REF="${VIDEOMEMORY_REPO_REF:-main}"
REPO_DIR="${VIDEOMEMORY_REPO_DIR:-$HOME/videomemory}"
VIDEOMEMORY_BASE="${VIDEOMEMORY_BASE:-http://127.0.0.1:5050}"
DOCKER_OPENCLAW_BASE="${VIDEOMEMORY_DOCKER_OPENCLAW_BASE:-http://host.docker.internal:5050}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_DIR="${VIDEOMEMORY_STATE_DIR:-$STATE_HOME/videomemory}"
LOG_FILE="$STATE_DIR/server.log"
PID_FILE="$STATE_DIR/server.pid"
SKIP_START=0
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
    --videomemory-base)
      VIDEOMEMORY_BASE="$2"
      shift 2
      ;;
    --docker-openclaw-base)
      DOCKER_OPENCLAW_BASE="$2"
      shift 2
      ;;
    --skip-start)
      SKIP_START=1
      shift 1
      ;;
    --skip-keys)
      SKIP_KEYS=1
      shift 1
      ;;
    --help|-h)
      cat <<'EOF'
Usage: install-videomemory.sh [options]

Options:
  --repo-url URL              VideoMemory git URL
  --repo-ref REF              Git branch/tag to use
  --repo-dir DIR              Checkout location
  --videomemory-base URL      Host URL where VideoMemory should be reachable
  --docker-openclaw-base URL  URL Dockerized OpenClaw should use to reach VideoMemory
  --skip-start                Do not attempt to launch VideoMemory
  --skip-keys                 Do not copy model API keys into VideoMemory
EOF
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

VENV_PYTHON="$REPO_DIR/.venv/bin/python"

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

[ -n "$CURL_BIN" ] || fail "curl is required"
[ -n "$GIT_BIN" ] || fail "git is required"
[ -n "$UV_BIN" ] || [ -n "$PYTHON_BIN" ] || fail "uv or python3 is required to launch VideoMemory without Docker"

ensure_repo() {
  if [ -d "$REPO_DIR/.git" ]; then
    log "Using existing repo at $REPO_DIR"
    if ! "$GIT_BIN" -C "$REPO_DIR" pull --ff-only origin "$REPO_REF" >/dev/null 2>&1; then
      log "Repo update skipped (non-fast-forward or local changes). Continuing with existing checkout."
    fi
    return 0
  fi

  log "Cloning VideoMemory from $REPO_URL into $REPO_DIR"
  mkdir -p "$(dirname "$REPO_DIR")"
  "$GIT_BIN" clone --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR" >/dev/null
}

healthcheck() {
  "$CURL_BIN" -fsS "$VIDEOMEMORY_BASE/api/health" >/dev/null 2>&1
}

pid_is_running() {
  pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1
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

start_local_videomemory() {
  mkdir -p "$STATE_DIR"

  if [ -f "$PID_FILE" ]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if pid_is_running "$existing_pid"; then
      log "VideoMemory process already running with pid $existing_pid"
      return 0
    fi
    rm -f "$PID_FILE"
  fi

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

start_videomemory_if_needed() {
  if healthcheck; then
    log "VideoMemory already reachable at $VIDEOMEMORY_BASE"
    return 0
  fi

  if [ "$SKIP_START" -eq 1 ]; then
    fail "VideoMemory is not reachable at $VIDEOMEMORY_BASE and --skip-start was set"
  fi

  prepare_runtime
  start_local_videomemory

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

ensure_repo
start_videomemory_if_needed
sync_model_keys

log "Install complete"
log "Repo dir: $REPO_DIR"
log "VideoMemory UI: $VIDEOMEMORY_BASE/devices"
log "VideoMemory log: $LOG_FILE"
log "Docker OpenClaw prompt: Please install and onboard VideoMemory by running VIDEOMEMORY_BASE=$DOCKER_OPENCLAW_BASE bash <(curl -fsSL $DOCKER_OPENCLAW_BASE/openclaw/bootstrap.sh). Then use VideoMemory from $DOCKER_OPENCLAW_BASE/openclaw/skill.md and use the videomemory task helper for any 'when X happens, do Y' request."
