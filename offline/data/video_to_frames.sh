#!/usr/bin/env bash
# Extract every Nth frame from all .mp4 files under offline/data/mp4/<name>/.
# Output: offline/data/frames/<name>/<video_stem>_000001.jpg, ...
#
# Usage (every_n defaults to 30; max_frames caps output frames per video, optional):
#   ./offline/scripts/video_to_frames.sh <every_n> <folder_name> [max_frames]
#   ./offline/scripts/video_to_frames.sh <folder_name> [every_n] [max_frames]
#
# Examples:
#   ./offline/scripts/video_to_frames.sh house_tour
#   ./offline/scripts/video_to_frames.sh 60 house_tour
#   ./offline/scripts/video_to_frames.sh house_tour 500          # every 30, max 500 frames
#   ./offline/scripts/video_to_frames.sh house_tour 60 500       # every 60, max 500
#   ./offline/scripts/video_to_frames.sh 60 house_tour 500

set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

if [[ "${1:-}" =~ ^[1-9][0-9]*$ ]]; then
  EVERY="$1"
  NAME="${2:?usage: $0 <every_n> <folder_name> [max_frames]}"
  MAX="${3:-}"
else
  NAME="${1:?usage: $0 <folder_name> [every_n] [max_frames]}"
  case $# in
    1) EVERY=30; MAX= ;;
    2) EVERY=30; MAX="$2" ;;   # max_frames only (subsampling stays 30)
    3) EVERY="$2"; MAX="$3" ;;
    *) die "expected 1–3 arguments after script name, got $(($# - 1))" ;;
  esac
fi

[[ "$EVERY" =~ ^[1-9][0-9]*$ ]] || die "every_n must be a positive integer (got $EVERY)"
if [[ -n "$MAX" ]]; then
  [[ "$MAX" =~ ^[1-9][0-9]*$ ]] || die "max_frames must be a positive integer (got $MAX)"
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO_ROOT/offline/data/mp4/$NAME"
DST="$REPO_ROOT/offline/data/frames/$NAME"

[[ -d "$SRC" ]] || die "missing directory: $SRC"
command -v ffmpeg >/dev/null || die "ffmpeg not in PATH"

shopt -s nullglob
videos=("$SRC"/*.mp4)
(( ${#videos[@]} > 0 )) || die "no .mp4 in $SRC"

mkdir -p "$DST"

FF_EXTRA=()
[[ -n "$MAX" ]] && FF_EXTRA+=(-frames:v "$MAX")

for v in "${videos[@]}"; do
  stem="$(basename "${v%.mp4}")"
  ffmpeg -hide_banner -loglevel error -stats -y -i "$v" \
    -vf "select=not(mod(n\\,$EVERY)),setpts=N/FRAME_RATE/TB" \
    -vsync vfr -q:v 2 \
    "${FF_EXTRA[@]}" \
    "$DST/${stem}_%06d.jpg"
done

echo "done: $DST"
