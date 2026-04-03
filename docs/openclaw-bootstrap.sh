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
EOF
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

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
DOCKER_BIN="$(find_bin docker /Applications/Docker.app/Contents/Resources/bin/docker || true)"
CURL_BIN="$(find_bin curl || true)"

[ -n "$CURL_BIN" ] || fail "curl is required"
[ -n "$GIT_BIN" ] || fail "git is required"
[ -n "$NODE_BIN" ] || [ -n "$PYTHON_BIN" ] || fail "node or python3 is required to merge OpenClaw config"

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

start_videomemory_if_needed() {
  if healthcheck; then
    log "VideoMemory already reachable at $VIDEOMEMORY_BASE"
    return 0
  fi

  if [ "$SKIP_START" -eq 1 ]; then
    fail "VideoMemory is not reachable at $VIDEOMEMORY_BASE and --skip-start was set"
  fi

  [ -n "$DOCKER_BIN" ] || fail "docker is required to launch VideoMemory automatically"

  ensure_repo

  COMPOSE_FILE="$REPO_DIR/docker-compose.core.yml"
  [ -f "$COMPOSE_FILE" ] || fail "Missing compose file: $COMPOSE_FILE"

  log "Launching VideoMemory with docker compose"
  "$DOCKER_BIN" compose -f "$COMPOSE_FILE" up -d --build >/dev/null

  log "Waiting for VideoMemory health at $VIDEOMEMORY_BASE"
  i=0
  while [ "$i" -lt 60 ]; do
    if healthcheck; then
      log "VideoMemory is healthy"
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done

  fail "VideoMemory did not become healthy at $VIDEOMEMORY_BASE"
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
}

pick_videomemory_base
start_videomemory_if_needed
install_openclaw_files
merge_openclaw_config
sync_model_keys

log "Bootstrap complete"
log "VideoMemory base: $VIDEOMEMORY_BASE"
log "OpenClaw home: $OPENCLAW_HOME"
log "Next prompt to OpenClaw: Please onboard to VideoMemory here $VIDEOMEMORY_BASE/openclaw/skill.md and use the videomemory task helper for any 'when X happens, do Y' request."
