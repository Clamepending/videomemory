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
UV_BIN="$(find_bin uv || true)"
SUDO_BIN="$(find_bin sudo || true)"

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

  ensure_repo
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

pick_videomemory_base
start_videomemory_if_needed
setup_tailscale_if_needed
install_openclaw_files
merge_openclaw_config
sync_model_keys

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
