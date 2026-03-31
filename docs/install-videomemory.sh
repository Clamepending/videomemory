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
DOCKER_BIN="$(find_bin docker /Applications/Docker.app/Contents/Resources/bin/docker || true)"
CURL_BIN="$(find_bin curl || true)"

[ -n "$CURL_BIN" ] || fail "curl is required"
[ -n "$GIT_BIN" ] || fail "git is required"

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

start_videomemory_if_needed() {
  if healthcheck; then
    log "VideoMemory already reachable at $VIDEOMEMORY_BASE"
    return 0
  fi

  if [ "$SKIP_START" -eq 1 ]; then
    fail "VideoMemory is not reachable at $VIDEOMEMORY_BASE and --skip-start was set"
  fi

  [ -n "$DOCKER_BIN" ] || fail "docker is required to launch VideoMemory automatically"

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

ensure_repo
start_videomemory_if_needed
sync_model_keys

log "Install complete"
log "Repo dir: $REPO_DIR"
log "VideoMemory UI: $VIDEOMEMORY_BASE/devices"
log "Docker OpenClaw prompt: Please install and onboard VideoMemory by running VIDEOMEMORY_BASE=$DOCKER_OPENCLAW_BASE bash <(curl -fsSL $DOCKER_OPENCLAW_BASE/openclaw/bootstrap.sh). Then use VideoMemory from $DOCKER_OPENCLAW_BASE/openclaw/skill.md and use the videomemory task helper for any 'when X happens, do Y' request."
