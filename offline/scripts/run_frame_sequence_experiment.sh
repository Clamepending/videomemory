#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./offline/scripts/run_frame_sequence_experiment.sh --video_name <name> --task "<task>" [--viewer_port <n>] [--model <name>]

Example:
  ./offline/scripts/run_frame_sequence_experiment.sh --video_name house_tour --task "count chairs" --viewer_port 8080
EOF
}

die() { echo "error: $*" >&2; exit 1; }

DATASET=""
TASK=""
PORT=8080
MODEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --video_name) DATASET="${2:-}"; shift 2 ;;
    --task) TASK="${2:-}"; shift 2 ;;
    --viewer_port|--port) PORT="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$DATASET" ]] || die "missing --video_name"
[[ -n "$TASK" ]] || die "missing --task"
[[ "$PORT" =~ ^[1-9][0-9]*$ ]] || die "invalid --viewer_port: $PORT"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
[[ -d "offline/data/frames/$DATASET" ]] || die "missing offline/data/frames/$DATASET"

CMD=(uv run python -m offline.experiments.videoingestor_on_frame_sequence "$DATASET" "$TASK")
[[ -n "$MODEL" ]] && CMD+=(--model "$MODEL")
"${CMD[@]}"

echo "open: http://localhost:$PORT/ui/?dataset=$DATASET"
cd offline
python3 -m http.server "$PORT"

