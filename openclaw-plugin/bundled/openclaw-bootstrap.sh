#!/usr/bin/env sh

set -eu

log() {
  printf '[videomemory-bootstrap] %s\n' "$*"
}

fail() {
  printf '[videomemory-bootstrap] ERROR: %s\n' "$*" >&2
  exit 1
}

REPO_URL="${VIDEOMEMORY_REPO_URL:-https://github.com/Clamepending/videomemory.git}"
REPO_REF="${VIDEOMEMORY_REPO_REF:-main}"
REPO_DIR="${VIDEOMEMORY_REPO_DIR:-$HOME/videomemory}"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
VIDEOMEMORY_BASE="${VIDEOMEMORY_BASE:-}"
BOT_ID="${VIDEOMEMORY_OPENCLAW_BOT_ID:-openclaw}"
TAILSCALE_AUTHKEY="${VIDEOMEMORY_TAILSCALE_AUTHKEY:-${TAILSCALE_AUTHKEY:-}}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_DIR="${VIDEOMEMORY_STATE_DIR:-$STATE_HOME/videomemory}"
LOG_FILE="$STATE_DIR/server.log"
PID_FILE="$STATE_DIR/server.pid"
TAILSCALE_UI_URL=""
SKIP_START=0
SKIP_KEYS=0
SKIP_TAILSCALE=0
SKIP_NOTIFY=0
SAFE_MODE=0
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
    --bot-id)
      BOT_ID="$2"
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
    --skip-tailscale)
      SKIP_TAILSCALE=1
      shift 1
      ;;
    --skip-notify)
      SKIP_NOTIFY=1
      shift 1
      ;;
    --safe)
      SAFE_MODE=1
      SKIP_KEYS=1
      SKIP_TAILSCALE=1
      SKIP_NOTIFY=1
      shift 1
      ;;
    --dry-run|--explain)
      DRY_RUN=1
      shift 1
      ;;
    --tailscale-authkey)
      TAILSCALE_AUTHKEY="$2"
      shift 2
      ;;
    --help|-h)
      cat <<'EOF'
Usage: openclaw-bootstrap.sh [options]

Options:
  --repo-url URL              VideoMemory git URL
  --repo-ref REF              Git branch/tag to use
  --repo-dir DIR              Checkout location
  --openclaw-home DIR         OpenClaw home directory
  --videomemory-base URL      VideoMemory base URL once running
  --bot-id ID                 bot_id to write into helper-created tasks
  --skip-start                Do not attempt to launch VideoMemory
  --skip-keys                 Do not copy model API keys into VideoMemory
  --skip-tailscale            Do not attempt to install/configure Tailscale
  --skip-notify               Do not send the UI link through Telegram
  --safe                      Agent-safe mode: no sudo, Tailscale setup, key sync, or Telegram notify
  --dry-run, --explain        Print the onboarding plan without making changes
  --tailscale-authkey KEY     Optional Tailscale auth key for noninteractive tailscale up
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

NODE_BIN="$(find_bin node || true)"
PYTHON_BIN="$(find_bin python3 || true)"
GIT_BIN="$(find_bin git || true)"
CURL_BIN="$(find_bin curl || true)"
UV_BIN="$(find_bin "$HOME/.local/bin/uv" /home/linuxbrew/.linuxbrew/bin/uv uv || true)"
SUDO_BIN="$(find_bin sudo || true)"
LSOF_BIN="$(find_bin lsof || true)"
SS_BIN="$(find_bin ss || true)"

[ -n "$CURL_BIN" ] || fail "curl is required"
[ -n "$GIT_BIN" ] || fail "git is required"
[ -n "$NODE_BIN" ] || [ -n "$PYTHON_BIN" ] || fail "node or python3 is required to merge OpenClaw config"
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

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return $?
  fi
  if [ -n "$SUDO_BIN" ] && "$SUDO_BIN" -n true >/dev/null 2>&1; then
    "$SUDO_BIN" "$@"
    return $?
  fi
  return 1
}

pick_videomemory_base() {
  if [ -n "$VIDEOMEMORY_BASE" ]; then
    log "Using configured VideoMemory base $VIDEOMEMORY_BASE"
    return 0
  fi

  for candidate in \
    "http://127.0.0.1:5050" \
    "http://localhost:5050" \
    "http://host.docker.internal:5050" \
    "http://videomemory:5050"
  do
    if "$CURL_BIN" -fsS "$candidate/api/health" >/dev/null 2>&1; then
      VIDEOMEMORY_BASE="$candidate"
      log "Detected VideoMemory at $VIDEOMEMORY_BASE"
      return 0
    fi
  done

  VIDEOMEMORY_BASE="http://127.0.0.1:5050"
  log "VideoMemory not yet reachable; defaulting bootstrap target to $VIDEOMEMORY_BASE"
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
      stop_pid_gracefully "$existing_pid" "stale VideoMemory process"
    fi
    rm -f "$PID_FILE"
  fi

  existing_listener_pid="$(listener_pid || true)"
  if [ -n "$existing_listener_pid" ] && pid_looks_like_videomemory "$existing_listener_pid"; then
    stop_pid_gracefully "$existing_listener_pid" "stale VideoMemory listener"
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

  ensure_repo
  prepare_runtime
  start_local_videomemory

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

install_tailscale_if_needed() {
  if [ "$SKIP_TAILSCALE" -eq 1 ]; then
    log "Skipping Tailscale install"
    return 0
  fi

  TAILSCALE_BIN="$(find_bin tailscale || true)"
  if [ -n "$TAILSCALE_BIN" ]; then
    log "Tailscale already installed at $TAILSCALE_BIN"
    return 0
  fi

  case "$(uname -s 2>/dev/null || printf 'unknown')" in
    Linux)
      mkdir -p "$STATE_DIR"
      INSTALL_SCRIPT="$STATE_DIR/install-tailscale.sh"
      if ! "$CURL_BIN" -fsSL https://tailscale.com/install.sh -o "$INSTALL_SCRIPT"; then
        log "Warning: could not download the Tailscale installer"
        return 0
      fi
      chmod +x "$INSTALL_SCRIPT"
      if run_privileged sh "$INSTALL_SCRIPT" >>"$LOG_FILE" 2>&1; then
        TAILSCALE_BIN="$(find_bin tailscale || true)"
        if [ -n "$TAILSCALE_BIN" ]; then
          log "Installed Tailscale successfully"
        fi
      else
        log "Warning: could not install Tailscale automatically. Run 'curl -fsSL https://tailscale.com/install.sh | sh' with root access."
      fi
      ;;
    *)
      log "Warning: automatic Tailscale install is only implemented for Linux. Install Tailscale manually on this machine."
      ;;
  esac
}

ensure_tailscaled_service() {
  TAILSCALE_BIN="$(find_bin tailscale || true)"
  [ -n "$TAILSCALE_BIN" ] || return 0

  if command -v systemctl >/dev/null 2>&1; then
    run_privileged systemctl enable --now tailscaled >>"$LOG_FILE" 2>&1 || true
    return 0
  fi

  if command -v service >/dev/null 2>&1; then
    run_privileged service tailscaled start >>"$LOG_FILE" 2>&1 || true
  fi
}

get_tailscale_ipv4() {
  TAILSCALE_BIN="$(find_bin tailscale || true)"
  [ -n "$TAILSCALE_BIN" ] || return 1
  "$TAILSCALE_BIN" ip -4 2>/dev/null | sed -n '1p'
}

setup_tailscale_if_needed() {
  if [ "$SKIP_TAILSCALE" -eq 1 ]; then
    return 0
  fi

  install_tailscale_if_needed
  ensure_tailscaled_service

  TAILSCALE_IP="$(get_tailscale_ipv4 || true)"
  if [ -n "$TAILSCALE_IP" ]; then
    TAILSCALE_UI_URL="http://$TAILSCALE_IP:5050/devices"
    log "Detected Tailscale UI URL: $TAILSCALE_UI_URL"
    return 0
  fi

  TAILSCALE_BIN="$(find_bin tailscale || true)"
  if [ -z "$TAILSCALE_BIN" ]; then
    log "Warning: Tailscale is not installed, so the tailnet UI link is unavailable."
    return 0
  fi

  if [ -n "$TAILSCALE_AUTHKEY" ]; then
    log "Connecting Tailscale with provided auth key"
    if run_privileged "$TAILSCALE_BIN" up --authkey="$TAILSCALE_AUTHKEY" --accept-routes >>"$LOG_FILE" 2>&1; then
      TAILSCALE_IP="$(get_tailscale_ipv4 || true)"
      if [ -n "$TAILSCALE_IP" ]; then
        TAILSCALE_UI_URL="http://$TAILSCALE_IP:5050/devices"
        log "Connected Tailscale UI URL: $TAILSCALE_UI_URL"
        return 0
      fi
    fi
    log "Warning: Tailscale auth key setup did not produce a tailnet IP. Check $LOG_FILE."
    return 0
  fi

  log "Tailscale is installed but not connected yet. Run 'sudo tailscale up' to get a tailnet VideoMemory UI link."
}

extract_telegram_bot_token() {
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
    printf '%s\n' "$TELEGRAM_BOT_TOKEN"
    return 0
  fi

  CONFIG_PATH="$OPENCLAW_HOME/openclaw.json"
  [ -f "$CONFIG_PATH" ] || return 0

  if [ -n "$NODE_BIN" ]; then
    OPENCLAW_CONFIG_PATH="$CONFIG_PATH" "$NODE_BIN" <<'EOF'
const fs = require("node:fs");

try {
  const config = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const token = config?.channels?.telegram?.botToken;
  if (typeof token === "string" && token.trim() && !token.includes("${")) {
    process.stdout.write(token.trim());
  }
} catch (_) {}
EOF
    return 0
  fi

  OPENCLAW_CONFIG_PATH="$CONFIG_PATH" "$PYTHON_BIN" <<'EOF'
import json
import os
from pathlib import Path

try:
    config = json.loads(Path(os.environ["OPENCLAW_CONFIG_PATH"]).read_text())
    token = (((config or {}).get("channels") or {}).get("telegram") or {}).get("botToken", "")
    token = str(token).strip()
    if token and "${" not in token:
        print(token, end="")
except Exception:
    pass
EOF
}

notify_user_with_ui_link() {
  ui_url="$1"
  [ -n "$ui_url" ] || return 0

  if [ "$SKIP_NOTIFY" -eq 1 ]; then
    log "Skipping Telegram notification"
    log "Reply to the user with this VideoMemory UI link: $ui_url"
    return 0
  fi

  message="VideoMemory is ready. Open the UI here: $ui_url"
  telegram_chat_id="${VIDEOMEMORY_BOOTSTRAP_NOTIFY_CHAT_ID:-${OPENCLAW_TELEGRAM_OWNER_ID:-}}"
  telegram_bot_token="$(extract_telegram_bot_token)"

  if [ -n "$telegram_chat_id" ] && [ -n "$telegram_bot_token" ]; then
    if "$CURL_BIN" -fsS -X POST "https://api.telegram.org/bot$telegram_bot_token/sendMessage" \
      --data-urlencode "chat_id=$telegram_chat_id" \
      --data-urlencode "text=$message" >/dev/null 2>&1; then
      log "Sent VideoMemory UI link to Telegram chat $telegram_chat_id"
    else
      log "Warning: failed to send the VideoMemory UI link to Telegram"
    fi
  fi

  log "Reply to the user with this VideoMemory UI link: $ui_url"
}

explain_plan() {
  effective_base="$VIDEOMEMORY_BASE"
  if [ -z "$effective_base" ]; then
    effective_base="auto-detect, then http://127.0.0.1:5050"
  fi

  log "VideoMemory onboarding plan"
  log "Mode: $([ "$SAFE_MODE" -eq 1 ] && printf 'safe' || printf 'standard')"
  log "Repo URL: $REPO_URL"
  log "Repo ref: $REPO_REF"
  log "Repo dir: $REPO_DIR"
  log "OpenClaw home: $OPENCLAW_HOME"
  log "VideoMemory base: $effective_base"
  log "State dir: $STATE_DIR"
  if [ "$SKIP_START" -eq 1 ]; then
    log "Will not start VideoMemory because --skip-start was set"
  else
    log "Will clone/update the repo if needed, prepare a local Python environment, and start VideoMemory on the host"
  fi
  log "Will install/update OpenClaw VideoMemory skill, helper, hook transform, and webhook config under $OPENCLAW_HOME"
  log "Will sync OpenClaw webhook settings into VideoMemory when OpenClaw config is present"
  if [ "$SKIP_KEYS" -eq 1 ]; then
    log "Will not copy model provider API keys into VideoMemory"
  else
    log "Will copy model provider API keys from the current environment into VideoMemory settings when present"
  fi
  if [ "$SKIP_TAILSCALE" -eq 1 ]; then
    log "Will not install or configure Tailscale, and will not use sudo for Tailscale setup"
  else
    log "May attempt Tailscale setup if available; this can require sudo on Linux"
  fi
  if [ "$SKIP_NOTIFY" -eq 1 ]; then
    log "Will not send a Telegram notification"
  else
    log "May send the resulting UI link to Telegram if bot credentials and chat id are already configured"
  fi
  log "No changes were made because --dry-run/--explain was set"
}

read_openclaw_webhook_config() {
  CONFIG_PATH="$OPENCLAW_HOME/openclaw.json"
  [ -f "$CONFIG_PATH" ] || return 0

  if [ -n "$NODE_BIN" ]; then
    OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_BOOTSTRAP_BOT_ID="$BOT_ID" "$NODE_BIN" <<'EOF'
const fs = require("node:fs");

try {
  const config = JSON.parse(fs.readFileSync(process.env.OPENCLAW_CONFIG_PATH, "utf8"));
  const gateway = typeof config?.gateway === "object" && config.gateway ? config.gateway : {};
  const hooks = typeof config?.hooks === "object" && config.hooks ? config.hooks : {};
  const mappings = Array.isArray(hooks.mappings) ? hooks.mappings : [];
  const mapping =
    mappings.find((entry) => entry && entry.id === "videomemory-alert") ||
    mappings.find((entry) => entry && entry.match && entry.match.path);
  const port = Number.isFinite(Number(gateway.port)) && Number(gateway.port) > 0 ? Number(gateway.port) : 18789;
  const hooksPath = typeof hooks.path === "string" && hooks.path.trim() ? hooks.path.trim() : "/hooks";
  const mappingPath =
    typeof mapping?.match?.path === "string" && mapping.match.path.trim()
      ? mapping.match.path.trim()
      : "videomemory-alert";
  const normalizedHooksPath = hooksPath.startsWith("/") ? hooksPath : `/${hooksPath}`;
  const normalizedMappingPath = mappingPath.replace(/^\/+/, "");
  const url = `http://127.0.0.1:${port}${normalizedHooksPath}/${normalizedMappingPath}`;
  const token = typeof hooks.token === "string" ? hooks.token.trim() : "";
  const botId = (process.env.OPENCLAW_BOOTSTRAP_BOT_ID || "").trim();
  process.stdout.write([url, token, botId].join("\n"));
} catch (_) {}
EOF
    return 0
  fi

  OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_BOOTSTRAP_BOT_ID="$BOT_ID" "$PYTHON_BIN" <<'EOF'
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
    bot_id = str(os.environ.get("OPENCLAW_BOOTSTRAP_BOT_ID") or "").strip()
    print(url)
    print(token)
    print(bot_id, end="")
except Exception:
    pass
EOF
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

install_openclaw_files() {
  ensure_repo

  copy_if_exists \
    "$REPO_DIR/docs/openclaw-videomemory-task-helper.mjs" \
    "$OPENCLAW_HOME/hooks/bin/videomemory-task-helper.mjs"
  copy_if_exists \
    "$REPO_DIR/deploy/openclaw-real-home/hooks/transforms/videomemory-alert.mjs" \
    "$OPENCLAW_HOME/hooks/transforms/videomemory-alert.mjs"
  copy_if_exists \
    "$REPO_DIR/docs/openclaw-skill.md" \
    "$OPENCLAW_HOME/workspace/skills/videomemory/SKILL.md"
}

merge_openclaw_config() {
  CONFIG_PATH="$OPENCLAW_HOME/openclaw.json"
  mkdir -p "$OPENCLAW_HOME"
  if [ -f "$CONFIG_PATH" ]; then
    cp "$CONFIG_PATH" "$CONFIG_PATH.bak.$(date +%Y%m%d%H%M%S)"
  fi

  if [ -n "$NODE_BIN" ]; then
    OPENCLAW_CONFIG_PATH="$CONFIG_PATH" \
    OPENCLAW_TRANSFORMS_DIR="$OPENCLAW_HOME/hooks/transforms" \
    OPENCLAW_BOOTSTRAP_BOT_ID="$BOT_ID" \
    "$NODE_BIN" <<'EOF'
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const configPath = process.env.OPENCLAW_CONFIG_PATH;
const transformsDir = process.env.OPENCLAW_TRANSFORMS_DIR;

let config = {};
if (fs.existsSync(configPath)) {
  try {
    config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch (error) {
    throw new Error(`Failed to parse ${configPath}: ${error.message}`);
  }
}

if (typeof config !== "object" || !config) {
  config = {};
}

const agents = config.agents && Array.isArray(config.agents.list) ? config.agents.list : [];
const defaultAgent = agents.find((agent) => agent && agent.default) || agents[0] || { id: "main" };
const defaultAgentId = defaultAgent.id || "main";

config.hooks = typeof config.hooks === "object" && config.hooks ? config.hooks : {};
config.hooks.enabled = true;
config.hooks.path = config.hooks.path || "/hooks";
config.hooks.transformsDir = transformsDir;
config.hooks.defaultSessionKey = config.hooks.defaultSessionKey || "hook:videomemory";
config.hooks.allowRequestSessionKey = false;
config.hooks.token =
  process.env.OPENCLAW_HOOKS_TOKEN ||
  config.hooks.token ||
  crypto.randomBytes(18).toString("hex");

const prefixes = new Set(Array.isArray(config.hooks.allowedSessionKeyPrefixes) ? config.hooks.allowedSessionKeyPrefixes : []);
prefixes.add("hook:");
prefixes.add("agent:");
config.hooks.allowedSessionKeyPrefixes = Array.from(prefixes);

const allowedAgentIds = new Set(Array.isArray(config.hooks.allowedAgentIds) ? config.hooks.allowedAgentIds : []);
allowedAgentIds.add(defaultAgentId);
config.hooks.allowedAgentIds = Array.from(allowedAgentIds);

const mapping = {
  id: "videomemory-alert",
  match: { path: "videomemory-alert" },
  action: "agent",
  agentId: defaultAgentId,
  wakeMode: "now",
  name: "VideoMemory",
  sessionKey: "hook:videomemory:{{io_id}}:{{task_id}}:{{event_id}}",
  deliver: false,
  transform: { module: "videomemory-alert.mjs" },
};

const existingMappings = Array.isArray(config.hooks.mappings) ? config.hooks.mappings : [];
const withoutOld = existingMappings.filter((entry) => entry && entry.id !== "videomemory-alert");
config.hooks.mappings = [...withoutOld, mapping];

fs.mkdirSync(path.dirname(configPath), { recursive: true });
fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ status: "ok", configPath, hookToken: config.hooks.token, agentId: defaultAgentId }));
EOF
    return 0
  fi

  OPENCLAW_CONFIG_PATH="$CONFIG_PATH" \
  OPENCLAW_TRANSFORMS_DIR="$OPENCLAW_HOME/hooks/transforms" \
  OPENCLAW_BOOTSTRAP_BOT_ID="$BOT_ID" \
  "$PYTHON_BIN" <<'EOF'
import json
import os
import secrets
from pathlib import Path

config_path = Path(os.environ["OPENCLAW_CONFIG_PATH"])
transforms_dir = os.environ["OPENCLAW_TRANSFORMS_DIR"]

if config_path.exists():
    config = json.loads(config_path.read_text())
else:
    config = {}

if not isinstance(config, dict):
    config = {}

agents = []
if isinstance(config.get("agents"), dict) and isinstance(config["agents"].get("list"), list):
    agents = config["agents"]["list"]

default_agent_id = "main"
for agent in agents:
    if isinstance(agent, dict) and agent.get("default"):
        default_agent_id = agent.get("id") or default_agent_id
        break
if default_agent_id == "main" and agents:
    first = agents[0]
    if isinstance(first, dict) and first.get("id"):
        default_agent_id = first["id"]

hooks = config.get("hooks")
if not isinstance(hooks, dict):
    hooks = {}
config["hooks"] = hooks

hooks["enabled"] = True
hooks["path"] = hooks.get("path") or "/hooks"
hooks["transformsDir"] = transforms_dir
hooks["defaultSessionKey"] = hooks.get("defaultSessionKey") or "hook:videomemory"
hooks["allowRequestSessionKey"] = False
hooks["token"] = os.environ.get("OPENCLAW_HOOKS_TOKEN") or hooks.get("token") or secrets.token_hex(18)

prefixes = hooks.get("allowedSessionKeyPrefixes")
if not isinstance(prefixes, list):
    prefixes = []
if "hook:" not in prefixes:
    prefixes.append("hook:")
if "agent:" not in prefixes:
    prefixes.append("agent:")
hooks["allowedSessionKeyPrefixes"] = prefixes

allowed_agents = hooks.get("allowedAgentIds")
if not isinstance(allowed_agents, list):
    allowed_agents = []
if default_agent_id not in allowed_agents:
    allowed_agents.append(default_agent_id)
hooks["allowedAgentIds"] = allowed_agents

mapping = {
    "id": "videomemory-alert",
    "match": {"path": "videomemory-alert"},
    "action": "agent",
    "agentId": default_agent_id,
    "wakeMode": "now",
    "name": "VideoMemory",
    "sessionKey": "hook:videomemory:{{io_id}}:{{task_id}}:{{event_id}}",
    "deliver": False,
    "transform": {"module": "videomemory-alert.mjs"},
}

mappings = hooks.get("mappings")
if not isinstance(mappings, list):
    mappings = []
mappings = [entry for entry in mappings if not (isinstance(entry, dict) and entry.get("id") == "videomemory-alert")]
mappings.append(mapping)
hooks["mappings"] = mappings

config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(config, indent=2) + "\n")
print(json.dumps({"status": "ok", "configPath": str(config_path), "hookToken": hooks["token"], "agentId": default_agent_id}))
EOF
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

warn_if_model_provider_needs_setup() {
  [ -n "$PYTHON_BIN" ] || return 0

  settings_json="$("$CURL_BIN" -fsS "$VIDEOMEMORY_BASE/api/settings" 2>/dev/null || true)"
  [ -n "$settings_json" ] || return 0

  warning_message="$(printf '%s' "$settings_json" | "$PYTHON_BIN" - "$VIDEOMEMORY_BASE" <<'EOF'
import json
import sys

base_url = sys.argv[1].rstrip("/")
try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)

settings = payload.get("settings") or {}

def is_set(key: str) -> bool:
    return bool((settings.get(key) or {}).get("is_set"))

model_name = str((settings.get("VIDEO_INGESTOR_MODEL") or {}).get("value") or "local-vllm").strip() or "local-vllm"
required_map = {
    "gemini-2.5-flash": "GOOGLE_API_KEY",
    "gemini-2.5-flash-lite": "GOOGLE_API_KEY",
    "gpt-4.1-nano": "OPENAI_API_KEY",
    "gpt-4o-mini": "OPENAI_API_KEY",
    "claude-sonnet-4-6": "ANTHROPIC_API_KEY",
    "claude-haiku-4-5": "ANTHROPIC_API_KEY",
    "claude-opus-4-6": "ANTHROPIC_API_KEY",
    "molmo-2-8b": "OPENROUTER_API_KEY",
    "qwen-2-vl-7b": "OPENROUTER_API_KEY",
    "phi-4-multimodal": "OPENROUTER_API_KEY",
    "mistral-small-3.1": "OPENROUTER_API_KEY",
    "qwen3-vl-8b": "OPENROUTER_API_KEY",
}
cloud_keys = [
    key for key in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
    if is_set(key)
]
required_setting = required_map.get(model_name)

if required_setting and not is_set(required_setting):
    print(
        f"Model '{model_name}' requires {required_setting}, but it is not configured yet. "
        f"Tell the user to open {base_url}/settings and save that key before creating tasks."
    )
elif model_name == "local-vllm" and not cloud_keys:
    print(
        f"No cloud model provider key is configured yet. If the user is not intentionally using a local vLLM server, "
        f"tell them to open {base_url}/settings and save a provider API key before creating tasks."
    )
EOF
)"

  if [ -n "$warning_message" ]; then
    log "Configuration warning: $warning_message"
    log "Reply to the user with this setup warning: $warning_message"
  fi
}

if [ "$DRY_RUN" -eq 1 ]; then
  explain_plan
  exit 0
fi

pick_videomemory_base
start_videomemory_if_needed
setup_tailscale_if_needed
install_openclaw_files
merge_openclaw_config
sync_openclaw_webhook_settings
sync_model_keys
warn_if_model_provider_needs_setup

USER_FACING_UI_URL="$VIDEOMEMORY_BASE/devices"
if [ -n "$TAILSCALE_UI_URL" ]; then
  USER_FACING_UI_URL="$TAILSCALE_UI_URL"
fi

log "Bootstrap complete"
log "VideoMemory base: $VIDEOMEMORY_BASE"
log "User-facing VideoMemory UI: $USER_FACING_UI_URL"
log "VideoMemory log: $LOG_FILE"
log "OpenClaw home: $OPENCLAW_HOME"
if [ -z "$TAILSCALE_UI_URL" ] && [ "$SKIP_TAILSCALE" -eq 0 ]; then
  log "Tailscale UI link unavailable yet. Finish 'sudo tailscale up' or provide --tailscale-authkey to make the UI reachable over Tailscale."
fi
notify_user_with_ui_link "$USER_FACING_UI_URL"
log "Next prompt to OpenClaw: Please onboard to VideoMemory here $VIDEOMEMORY_BASE/openclaw/skill.md and use the videomemory task helper for any 'when X happens, do Y' request."
