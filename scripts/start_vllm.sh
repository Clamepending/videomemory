#!/usr/bin/env bash
# Start local vLLM server for VideoMemory.
# VideoMemory uses whatever model this server loads (see VLLM_MODEL).
# Usage: sourced from start.sh, or run directly.

set -e
: "${REPO_ROOT:="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"

VLLM_CONTAINER_NAME="vllm-qwen"
VLLM_PORT="${VLLM_PORT:-8100}"
VLLM_IMAGE="vllm/vllm-openai:latest"
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-VL-8B-Instruct-FP8}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"

bold()  { printf "\033[1m%s\033[0m" "$*"; }
green() { printf "\033[1;32m%s\033[0m" "$*"; }
dim()   { printf "\033[2m%s\033[0m" "$*"; }

# Check if vLLM container is already running
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$VLLM_CONTAINER_NAME"; then
  echo "$(green '✓') Local vLLM already running ($VLLM_CONTAINER_NAME) on port $VLLM_PORT"
  export VLLM_LOCAL_URL="http://localhost:${VLLM_PORT}"
  return 0 2>/dev/null || exit 0
fi

# Only prompt if stdin is a terminal; skip entirely when non-interactive unless forced
if [[ ! -t 0 ]] && [[ "${VLLM_AUTO_START:-0}" != "1" ]]; then
  return 0 2>/dev/null || exit 0
fi

if [[ -t 0 ]]; then
  echo ""
  echo "$(bold 'Local vLLM server')"
  echo "Run a local vision model so VideoMemory can use it instead of cloud APIs (Gemini, OpenAI, etc.)."
  echo ""
  read -rp "Launch local vLLM server? [Y/n] " launch_vllm
  if [[ "${launch_vllm,,}" == "n" ]]; then
    echo "$(dim 'Skipping local vLLM — VideoMemory will use cloud API keys from Settings.')"
    return 0 2>/dev/null || exit 0
  fi
fi

# Require Docker
if ! command -v docker &>/dev/null; then
  echo "Docker is required to run local vLLM. Install Docker and try again."
  return 1 2>/dev/null || exit 1
fi

# Require nvidia runtime for GPU
if ! docker info 2>/dev/null | grep -q "nvidia"; then
  echo "NVIDIA container runtime not found. Install nvidia-container-toolkit for GPU support."
  return 1 2>/dev/null || exit 1
fi

# Remove existing container so we always create fresh with current model
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$VLLM_CONTAINER_NAME"; then
  echo "Removing existing vLLM container (to use current model: $VLLM_MODEL)..."
  docker rm -f "$VLLM_CONTAINER_NAME" >/dev/null 2>&1 || true
fi

# Pull image if needed (runs in background to avoid blocking)
if ! docker image inspect "$VLLM_IMAGE" &>/dev/null; then
  echo "Pulling vLLM image (this may take a few minutes)..."
  docker pull "$VLLM_IMAGE" || { echo "Failed to pull $VLLM_IMAGE"; return 1 2>/dev/null || exit 1; }
fi

# Create and run new container
echo "Starting local vLLM with $VLLM_MODEL..."
mkdir -p "$HF_CACHE"
docker run -d \
  --name "$VLLM_CONTAINER_NAME" \
  --runtime nvidia \
  --gpus '"device=0"' \
  --network host \
  -v "${HF_CACHE}:/root/.cache/huggingface" \
  --ipc=host \
  "$VLLM_IMAGE" \
  --model "$VLLM_MODEL" \
  --quantization fp8 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.9 \
  --trust-remote-code \
  --port "$VLLM_PORT" \
  >/dev/null 2>&1

echo "$(green '✓') Local vLLM starting on port $VLLM_PORT (model loading takes ~1 min)"
echo "  API: $(bold "http://localhost:${VLLM_PORT}/v1/chat/completions")"
export VLLM_LOCAL_URL="http://localhost:${VLLM_PORT}"
return 0 2>/dev/null || exit 0
