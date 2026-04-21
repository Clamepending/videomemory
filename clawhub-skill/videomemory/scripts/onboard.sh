#!/usr/bin/env sh

set -eu

log() {
  printf '[videomemory-skill] %s\n' "$*" >&2
}

fail() {
  printf '[videomemory-skill] ERROR: %s\n' "$*" >&2
  exit 1
}

REPO_URL="${VIDEOMEMORY_REPO_URL:-https://github.com/Clamepending/videomemory.git}"
REPO_REF="${VIDEOMEMORY_REPO_REF:-v0.1.2}"
REPO_DIR="${VIDEOMEMORY_REPO_DIR:-$HOME/videomemory}"
EXPECTED_COMMIT="${VIDEOMEMORY_EXPECTED_COMMIT:-1e25cdd6d5ac361300938246978ad2c4c5bae7d5}"
BOOTSTRAP_SCRIPT="$REPO_DIR/docs/openclaw-bootstrap.sh"

find_bin() {
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_repo_script() {
  GIT_BIN="$(find_bin git || true)"
  [ -n "$GIT_BIN" ] || fail "git is required to fetch VideoMemory"

  if [ -f "$BOOTSTRAP_SCRIPT" ]; then
    verify_expected_commit
    return 0
  fi

  if [ -e "$REPO_DIR" ]; then
    fail "$REPO_DIR exists but does not contain docs/openclaw-bootstrap.sh"
  fi

  log "Cloning VideoMemory $REPO_REF into $REPO_DIR"
  mkdir -p "$(dirname "$REPO_DIR")"
  "$GIT_BIN" clone --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR" >/dev/null
  verify_expected_commit
}

verify_expected_commit() {
  if [ -z "$EXPECTED_COMMIT" ]; then
    return 0
  fi

  actual_commit="$("$GIT_BIN" -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)"
  [ -n "$actual_commit" ] || fail "could not determine VideoMemory repo commit"

  case "$actual_commit" in
    "$EXPECTED_COMMIT"*)
      log "Verified VideoMemory commit $actual_commit"
      ;;
    *)
      fail "VideoMemory repo commit $actual_commit did not match expected $EXPECTED_COMMIT"
      ;;
  esac
}

ensure_repo_script

exec sh "$BOOTSTRAP_SCRIPT" \
  --repo-url "$REPO_URL" \
  --repo-ref "$REPO_REF" \
  --repo-dir "$REPO_DIR" \
  "$@"
