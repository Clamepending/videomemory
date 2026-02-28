#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_UNIT=1
RUN_DOCKER=1
RUN_PHONE_DEMO=1
NO_BUILD=0
KEEP_STACKS=0
WAIT_TIMEOUT_S=180
LOG_DIR="$ROOT_DIR/data/e2e-logs/$(date +"%Y%m%d-%H%M%S")"

TOTAL_STEPS=0
FAIL_COUNT=0
FAILED_STEPS=()
ACTIVE_COMPOSE=""

usage() {
  cat <<'EOF'
Usage: bash deploy/test-e2e-suite.sh [options]

Options:
  --skip-unit         Skip Python tests.
  --skip-docker       Skip Docker stack smoke tests.
  --skip-phone-demo   Skip deploy/test-openclaw-phone-demo.sh.
  --no-build          Use docker compose up -d (skip --build).
  --keep-stacks       Do not tear down docker stacks after each suite.
  --timeout N         HTTP health wait timeout in seconds (default: 180).
  --log-dir PATH      Directory for step logs (default under data/e2e-logs).
  -h, --help          Show this help.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --skip-unit)
      RUN_UNIT=0
      shift
      ;;
    --skip-docker)
      RUN_DOCKER=0
      shift
      ;;
    --skip-phone-demo)
      RUN_PHONE_DEMO=0
      shift
      ;;
    --no-build)
      NO_BUILD=1
      shift
      ;;
    --keep-stacks)
      KEEP_STACKS=1
      shift
      ;;
    --timeout)
      if (( $# < 2 )); then
        echo "Missing value for --timeout" >&2
        exit 2
      fi
      WAIT_TIMEOUT_S="$2"
      shift 2
      ;;
    --log-dir)
      if (( $# < 2 )); then
        echo "Missing value for --log-dir" >&2
        exit 2
      fi
      LOG_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

mkdir -p "$LOG_DIR"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    return 1
  fi
}

compose_up() {
  local compose_file="$1"
  if (( NO_BUILD == 1 )); then
    docker compose -f "$compose_file" up -d
  else
    docker compose -f "$compose_file" up -d --build
  fi
}

compose_down() {
  local compose_file="$1"
  docker compose -f "$compose_file" down --remove-orphans >/dev/null 2>&1 || true
}

cleanup_on_exit() {
  if (( KEEP_STACKS == 0 )) && [[ -n "$ACTIVE_COMPOSE" ]]; then
    echo
    echo "[cleanup] tearing down $ACTIVE_COMPOSE"
    compose_down "$ACTIVE_COMPOSE"
  fi
}

trap cleanup_on_exit EXIT INT TERM

wait_http() {
  local url="$1"
  local timeout_s="${2:-$WAIT_TIMEOUT_S}"
  local deadline=$((SECONDS + timeout_s))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for $url (${timeout_s}s)" >&2
  return 1
}

step_slug() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-'
}

capture_compose_debug() {
  local compose_file="$1"
  local slug="$2"
  if [[ -z "$compose_file" ]]; then
    return 0
  fi
  docker compose -f "$compose_file" ps --all >"$LOG_DIR/${slug}.compose-ps.log" 2>&1 || true
  docker compose -f "$compose_file" logs --no-color --tail 400 >"$LOG_DIR/${slug}.compose-logs.log" 2>&1 || true
}

run_with_log() {
  local log_file="$1"
  shift
  "$@" 2>&1 | tee "$log_file"
  local rc="${PIPESTATUS[0]}"
  return "$rc"
}

run_step() {
  local name="$1"
  shift
  TOTAL_STEPS=$((TOTAL_STEPS + 1))
  local slug
  slug="$(step_slug "$name")"
  local log_file="$LOG_DIR/${TOTAL_STEPS}-${slug}.log"
  echo
  echo "=== [$TOTAL_STEPS] $name ==="
  if run_with_log "$log_file" "$@"; then
    echo "PASS: $name"
    echo "Log: $log_file"
    return 0
  fi

  local rc
  rc=$?
  echo "FAIL: $name (exit $rc)"
  echo "Log: $log_file"
  capture_compose_debug "$ACTIVE_COMPOSE" "${TOTAL_STEPS}-${slug}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILED_STEPS+=("$name (exit $rc)")
  return 0
}

preflight() {
  require_cmd uv &&
    require_cmd python &&
    require_cmd curl &&
    require_cmd docker &&
    require_cmd find
  docker info >/dev/null
}

print_versions() {
  uv --version
  python --version
  docker --version
  docker compose version
  curl --version | head -n 1
}

run_python_suite() {
  local rc=0

  uv sync --frozen --no-dev || return 1

  PYTHONPATH="$ROOT_DIR" uv run python -m compileall -q flask_app videomemory tests || rc=1
  PYTHONPATH="$ROOT_DIR" uv run python -c "import videomemory; import flask_app.app; print('import smoke ok')" || rc=1
  PYTHONPATH="$ROOT_DIR" uv run python -m unittest discover -s tests -p 'test_*.py' -v || rc=1

  return "$rc"
}

run_eventmode_suite() {
  local compose_file="docker-compose.eventmode.yml"
  local rc=0
  ACTIVE_COMPOSE="$compose_file"
  compose_down "$compose_file"
  compose_up "$compose_file" || rc=1
  if (( rc == 0 )); then
    wait_http "http://127.0.0.1:8785/api/health" "$WAIT_TIMEOUT_S" || rc=1
    wait_http "http://127.0.0.1:18789/health" "$WAIT_TIMEOUT_S" || rc=1
  fi
  if (( rc == 0 )); then
    bash deploy/test-eventmode-cloud.sh || rc=1
    bash deploy/test-eventmode-mcp.sh || rc=1
  fi
  if (( KEEP_STACKS == 0 )); then
    compose_down "$compose_file"
  fi
  ACTIVE_COMPOSE=""
  return "$rc"
}

run_openclaw_suite() {
  local compose_file="docker-compose.openclaw.yml"
  local rc=0
  ACTIVE_COMPOSE="$compose_file"
  compose_down "$compose_file"
  compose_up "$compose_file" || rc=1
  if (( rc == 0 )); then
    wait_http "http://127.0.0.1:5050/api/health" "$WAIT_TIMEOUT_S" || rc=1
    wait_http "http://127.0.0.1:8765/healthz" "$WAIT_TIMEOUT_S" || rc=1
    wait_http "http://127.0.0.1:8091/healthz" "$WAIT_TIMEOUT_S" || rc=1
    wait_http "http://127.0.0.1:28789/" "$WAIT_TIMEOUT_S" || rc=1
  fi
  if (( rc == 0 )); then
    BASE_OC="http://127.0.0.1:28789" bash deploy/test-openclaw-stack.sh || rc=1
    if (( RUN_PHONE_DEMO == 1 )); then
      BASE_OC="http://127.0.0.1:28789" LAPTOP_HOST="127.0.0.1" bash deploy/test-openclaw-phone-demo.sh || rc=1
    fi
  fi
  if (( KEEP_STACKS == 0 )); then
    compose_down "$compose_file"
  fi
  ACTIVE_COMPOSE=""
  return "$rc"
}

run_adminagent_suite() {
  local compose_file="docker-compose.adminagent.yml"
  local rc=0
  ACTIVE_COMPOSE="$compose_file"
  compose_down "$compose_file"
  compose_up "$compose_file" || rc=1
  if (( rc == 0 )); then
    wait_http "http://127.0.0.1:5050/api/health" "$WAIT_TIMEOUT_S" || rc=1
    wait_http "http://127.0.0.1:8765/healthz" "$WAIT_TIMEOUT_S" || rc=1
    wait_http "http://127.0.0.1:18789/health" "$WAIT_TIMEOUT_S" || rc=1
  fi
  if (( rc == 0 )); then
    bash deploy/test-adminagent-stack.sh || rc=1
  fi
  if (( KEEP_STACKS == 0 )); then
    compose_down "$compose_file"
  fi
  ACTIVE_COMPOSE=""
  return "$rc"
}

run_step "Preflight command checks" preflight
run_step "Tool versions" print_versions

if (( RUN_UNIT == 1 )); then
  run_step "Python suite (uv sync, compileall, import smoke, unittest discover)" run_python_suite
fi

if (( RUN_DOCKER == 1 )); then
  run_step "Event Mode stack E2E" run_eventmode_suite
  run_step "OpenClaw stack E2E" run_openclaw_suite
  run_step "AdminAgent stack E2E" run_adminagent_suite
fi

echo
echo "=== Summary ==="
echo "Total steps: $TOTAL_STEPS"
echo "Failed steps: $FAIL_COUNT"
echo "Logs: $LOG_DIR"
if (( FAIL_COUNT > 0 )); then
  local_item=""
  for local_item in "${FAILED_STEPS[@]}"; do
    echo " - $local_item"
  done
  exit 1
fi

echo "All suites passed."
exit 0
