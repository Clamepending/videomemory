#!/usr/bin/env bash
set -euo pipefail

TARGET=""
REPLY_TO=""
IO_ID="0"
BASE_URL="http://127.0.0.1:5050"
OUT_PATH="${HOME}/.openclaw/workspace/videomemory-preview.jpg"
OPENCLAW_BIN="${HOME}/.npm-global/bin/openclaw"
SEND_TIMEOUT_SECONDS="${VIDEOMEMORY_OPENCLAW_SEND_TIMEOUT_SECONDS:-6}"

usage() {
  cat <<'EOF'
Usage:
  openclaw_send_current_camera_image.sh --target <telegram-chat-id> [--reply-to <message-id>] [--io-id <io-id>] [--base-url <url>] [--out <path>]

Behavior:
  1. Try VideoMemory fresh capture first.
  2. Fall back to VideoMemory preview.
  3. Fall back to direct USB capture with ffmpeg.
  4. Try replying with media first when --reply-to is provided.
  5. If reply-to send fails or times out, retry as a plain media send.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --reply-to)
      REPLY_TO="${2:-}"
      shift 2
      ;;
    --io-id)
      IO_ID="${2:-}"
      shift 2
      ;;
    --base-url)
      BASE_URL="${2:-}"
      shift 2
      ;;
    --out)
      OUT_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${TARGET}" ]]; then
  echo "Missing required --target" >&2
  usage >&2
  exit 2
fi

mkdir -p "$(dirname "${OUT_PATH}")"

capture_fresh() {
  curl -fsSL -X POST "${BASE_URL}/api/device/${IO_ID}/capture" -o "${OUT_PATH}"
}

capture_preview() {
  curl -fsSL "${BASE_URL}/api/device/${IO_ID}/preview" -o "${OUT_PATH}"
}

capture_fallback() {
  ffmpeg -nostdin -loglevel error -f v4l2 -i /dev/video0 -frames:v 1 -update 1 -y "${OUT_PATH}"
}

if ! capture_fresh; then
  if ! capture_preview; then
    capture_fallback
  fi
fi

if [[ ! -s "${OUT_PATH}" ]]; then
  echo '{"status":"error","error":"camera capture produced no image"}' >&2
  exit 1
fi

run_send() {
  local -a cmd=("${OPENCLAW_BIN}" message send --channel telegram --target "${TARGET}" --media "${OUT_PATH}" --json)
  if [[ -n "${1:-}" ]]; then
    cmd+=(--reply-to "${1}")
  fi
  timeout "${SEND_TIMEOUT_SECONDS}" "${cmd[@]}"
}

send_output=""
if [[ -n "${REPLY_TO}" ]]; then
  if send_output="$(run_send "${REPLY_TO}" 2>&1)" && grep -q '"ok"[[:space:]]*:[[:space:]]*true' <<<"${send_output}"; then
    printf '%s\n' "${send_output}"
    exit 0
  fi
fi

send_output="$(run_send "" 2>&1)"
printf '%s\n' "${send_output}"
grep -q '"ok"[[:space:]]*:[[:space:]]*true' <<<"${send_output}"
