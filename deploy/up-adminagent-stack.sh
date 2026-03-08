#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

detect_lan_ip() {
  # macOS common Wi-Fi/Ethernet interfaces.
  if command -v ipconfig >/dev/null 2>&1; then
    for iface in en0 en1 en2; do
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      if [[ -n "$ip" ]]; then
        printf '%s\n' "$ip"
        return 0
      fi
    done
  fi

  # Linux fallback.
  if command -v ip >/dev/null 2>&1; then
    ip route get 1.1.1.1 2>/dev/null | awk '
      {
        for (i = 1; i <= NF; i++) {
          if ($i == "src" && (i + 1) <= NF) {
            print $(i + 1)
            exit
          }
        }
      }
    '
    return 0
  fi

  # Generic fallback: first private IPv4 address.
  if command -v ifconfig >/dev/null 2>&1; then
    ifconfig | awk '
      /inet / {
        ip = $2
        if (ip ~ /^10\./ || ip ~ /^192\.168\./ || ip ~ /^172\.(1[6-9]|2[0-9]|3[0-1])\./) {
          print ip
          exit
        }
      }
    '
  fi
}

find_simpleagent_repo() {
  if [[ -n "${SIMPLEAGENT_REPO:-}" ]]; then
    printf '%s\n' "$SIMPLEAGENT_REPO"
    return 0
  fi

  if [[ -d "$REPO_ROOT/../simpleagent/.git" ]]; then
    printf '%s\n' "$REPO_ROOT/../simpleagent"
    return 0
  fi

  if [[ -d "$REPO_ROOT/../adminagent/.git" ]]; then
    printf '%s\n' "$REPO_ROOT/../adminagent"
    return 0
  fi

  return 1
}

LAN_IP="$(detect_lan_ip | tr -d '[:space:]')"
if [[ -z "$LAN_IP" ]]; then
  echo "Could not auto-detect LAN IP. Set RTMP_SERVER_HOST manually and retry."
  exit 1
fi

SIMPLEAGENT_REPO_PATH="$(find_simpleagent_repo || true)"
if [[ -z "$SIMPLEAGENT_REPO_PATH" ]]; then
  echo "Could not find SimpleAgent repo. Expected ../simpleagent or ../adminagent."
  exit 1
fi

UPSTREAM_REF="${SIMPLEAGENT_UPSTREAM_REF:-origin/main}"
UPSTREAM_WORKTREE="$REPO_ROOT/.cache/simpleagent-upstream"
mkdir -p "$REPO_ROOT/.cache"

echo "Refreshing SimpleAgent from upstream ($UPSTREAM_REF) using $SIMPLEAGENT_REPO_PATH"
git -C "$SIMPLEAGENT_REPO_PATH" fetch origin main --prune
if [[ -e "$UPSTREAM_WORKTREE" ]]; then
  git -C "$SIMPLEAGENT_REPO_PATH" worktree remove --force "$UPSTREAM_WORKTREE" 2>/dev/null || rm -rf "$UPSTREAM_WORKTREE"
fi
git -C "$SIMPLEAGENT_REPO_PATH" worktree add --force --detach "$UPSTREAM_WORKTREE" "$UPSTREAM_REF" >/dev/null
SIMPLEAGENT_SHA="$(git -C "$UPSTREAM_WORKTREE" rev-parse --short HEAD)"
echo "Using SimpleAgent upstream commit: $SIMPLEAGENT_SHA"

export RTMP_SERVER_HOST="$LAN_IP"
export SIMPLEAGENT_BUILD_CONTEXT="$UPSTREAM_WORKTREE"
echo "Using RTMP_SERVER_HOST=$RTMP_SERVER_HOST"

docker compose -f docker-compose.adminagent.yml up -d --build

SIMPLEAGENT_BASE="${SIMPLEAGENT_BASE:-http://127.0.0.1:18889}"
BOT_ID="${VIDEOMEMORY_OPENCLAW_BOT_ID:-videomemory}"

for _ in $(seq 1 30); do
  if curl -fsS "$SIMPLEAGENT_BASE/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

BOTS_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "$SIMPLEAGENT_BASE/api/bots" || true)"
if [[ "$BOTS_STATUS" == "200" ]]; then
  CREATE_CODE="$(curl -sS -o /tmp/simpleagent-create-bot.out -w '%{http_code}' \
    -X POST "$SIMPLEAGENT_BASE/api/bots" \
    -H 'Content-Type: application/json' \
    -d "{\"bot_id\":\"$BOT_ID\",\"name\":\"VideoMemory\",\"model\":\"gpt-5\"}" || true)"

  if [[ "$CREATE_CODE" == "200" || "$CREATE_CODE" == "409" ]]; then
    echo "SimpleAgent bot ready: $BOT_ID"
  else
    echo "Warning: failed to ensure SimpleAgent bot '$BOT_ID' (HTTP $CREATE_CODE)"
  fi
elif [[ "$BOTS_STATUS" == "404" ]]; then
  echo "SimpleAgent upstream is in single-bot mode (/api/bots unavailable); skipping bot bootstrap"
else
  echo "Warning: unexpected /api/bots status ($BOTS_STATUS); skipping bot bootstrap"
fi

echo "SimpleAgent UI: $SIMPLEAGENT_BASE"
