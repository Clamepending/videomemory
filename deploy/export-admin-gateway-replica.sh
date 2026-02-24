#!/usr/bin/env bash
set -euo pipefail

# Export the admin gateway replica into a standalone repo working tree.
# Usage:
#   bash deploy/export-admin-gateway-replica.sh /tmp/videomemory-admin-gateway-replica

DEST="${1:-}"
if [[ -z "$DEST" ]]; then
  echo "Usage: $0 /path/to/output-dir" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p "$DEST"

cp -R admin_gateway_replica "$DEST"/
cp docker-compose.replica.yml "$DEST"/
cp deploy/test-replica-stack.sh "$DEST"/
cp deploy/test-replica-stack-internal.sh "$DEST"/

cat > "$DEST/README.md" <<'EOF'
# VideoMemory Admin Gateway Replica (Extracted)

This is the standalone OpenClaw-like gateway test harness extracted from the
VideoMemory monorepo. It receives VideoMemory webhook alerts and forwards them
to VideoMemory's `/chat` endpoint (Google ADK admin agent).

## Contents

- `admin_gateway_replica/` service source + Dockerfile
- `docker-compose.replica.yml` example stack (references a VideoMemory service)
- smoke test scripts

## Next steps

1. Initialize a git repo here: `git init`
2. Adjust `docker-compose.replica.yml` image/build references as needed
3. Add CI for unit tests and smoke tests
EOF

echo "Exported admin gateway replica files to: $DEST"
