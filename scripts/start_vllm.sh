#!/usr/bin/env bash
# Start local vLLM server for VideoMemory.
# VideoMemory uses whatever model this server loads (see VLLM_MODEL).
# Usage: sourced from start.sh, or run directly.

set -e
: "${REPO_ROOT:="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"

VLLM_CONTAINER_NAME="vllm-qwen"
VLLM_PORT="${VLLM_PORT:-8100}"
VLLM_IMAGE="vllm/vllm-openai:latest"
# Don't set default here - we prompt for model when interactive
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"

bold()   { printf "\033[1m%s\033[0m" "$*"; }
green()  { printf "\033[1;32m%s\033[0m" "$*"; }
red()    { printf "\033[1;31m%s\033[0m" "$*"; }
dim()    { printf "\033[2m%s\033[0m" "$*"; }

VLLM_ALREADY_RUNNING=0
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$VLLM_CONTAINER_NAME"; then
  VLLM_ALREADY_RUNNING=1
fi

# Only prompt if stdin is a terminal; skip entirely when non-interactive unless forced
if [[ ! -t 0 ]] && [[ "${VLLM_AUTO_START:-0}" != "1" ]]; then
  if [[ $VLLM_ALREADY_RUNNING -eq 1 ]]; then
    echo "$(green '✓') Local vLLM already running ($VLLM_CONTAINER_NAME) on port $VLLM_PORT"
    export VLLM_LOCAL_URL="http://localhost:${VLLM_PORT}"
  fi
  return 0 2>/dev/null || exit 0
fi

if [[ -t 0 ]]; then
  echo ""
  echo "$(bold 'Local vLLM server')"
  if [[ $VLLM_ALREADY_RUNNING -eq 1 ]]; then
    echo "$(green '✓') vLLM already running on port $VLLM_PORT"
    echo ""
    read -rp "Restart with a different model? [y/N] " restart_vllm
    if [[ "${restart_vllm,,}" != "y" ]]; then
      echo "$(dim 'Keeping current vLLM instance.')"
      export VLLM_LOCAL_URL="http://localhost:${VLLM_PORT}"
      return 0 2>/dev/null || exit 0
    fi
    # User wants to restart; remove container so we continue to model selection
    docker rm -f "$VLLM_CONTAINER_NAME" 2>/dev/null || true
    VLLM_ALREADY_RUNNING=0
  else
    echo "Run a local vision model so VideoMemory can use it instead of cloud APIs (Gemini, OpenAI, etc.)."
    echo ""
    read -rp "Launch local vLLM server? [Y/n] " launch_vllm
    if [[ "${launch_vllm,,}" == "n" ]]; then
      echo "$(dim 'Skipping local vLLM — VideoMemory will use cloud API keys from Settings.')"
      return 0 2>/dev/null || exit 0
    fi
  fi

  # Model selection (skip only if VLLM_MODEL explicitly set via env)
  if [[ -z "${VLLM_MODEL:+x}" ]]; then
    echo ""
    echo "$(bold 'Select model:')"
    echo "  1) Qwen3-VL-8B-Instruct-FP8 (~12GB VRAM)"
    echo "  2) Qwen3-VL-30B-A3B-Instruct (~24GB×4+ GPUs)"
    echo "  3) Phi-4-reasoning-vision-15B (~30GB VRAM)"
    echo "  4) Mistral-Small-3.1-24B-Instruct (~55GB VRAM)"
    echo "  5) Gemma-3-12B-IT (~24GB VRAM)"
    echo "  6) Molmo-7B-D-0924 (~12GB VRAM)"
    echo ""
    read -rp "Choice [1/2/3/4/5/6] (default: 1): " model_choice
    model_choice="${model_choice:-1}"
    case "$model_choice" in
      1) VLLM_MODEL="Qwen/Qwen3-VL-8B-Instruct-FP8" ;;
      2) VLLM_MODEL="Qwen/Qwen3-VL-30B-A3B-Instruct" ;;
      3) VLLM_MODEL="microsoft/Phi-4-reasoning-vision-15B" ;;
      4) VLLM_MODEL="mistralai/Mistral-Small-3.1-24B-Instruct-2503" ;;
      5) VLLM_MODEL="google/gemma-3-12b-it" ;;
      6) VLLM_MODEL="allenai/Molmo-7B-D-0924" ;;
      *) echo "Invalid choice. Using default (8B)."; VLLM_MODEL="Qwen/Qwen3-VL-8B-Instruct-FP8" ;;
    esac
    echo "$(dim "Selected: $VLLM_MODEL")"
  fi
fi

# Default model when not set (non-interactive or VLLM_MODEL from env)
VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-VL-8B-Instruct-FP8}"

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

# Extra vLLM args: 8B needs runtime fp8; 30B and Phi-4 use BF16 (no fp8)
if [[ "$VLLM_MODEL" == *"30B"* ]]; then
  # 30B needs multi-GPU. TP size must divide attention heads (32 for this model): valid 1,2,4,8.
  # Use largest valid TP <= GPU count.
  if [[ -n "${VLLM_TENSOR_PARALLEL_SIZE:-}" ]]; then
    VLLM_TP="$VLLM_TENSOR_PARALLEL_SIZE"
  else
    GPU_COUNT=$(nvidia-smi -L 2>/dev/null | wc -l)
    [[ "$GPU_COUNT" -lt 1 ]] && GPU_COUNT=1
    # Valid TP for 32 heads: 1,2,4,8. Pick largest <= GPU_COUNT.
    for tp in 8 4 2 1; do
      if [[ "$tp" -le "$GPU_COUNT" ]]; then
        VLLM_TP=$tp
        break
      fi
    done
    VLLM_TP="${VLLM_TP:-1}"
  fi
  VLLM_GPUS="all"
  # 30B: image-only (VideoMemory sends frames), async scheduling, lower memory for multi-GPU stability
  VLLM_EXTRA_ARGS=(
    --limit-mm-per-prompt '{"image": 4, "video": 0}'
    --async-scheduling
    --gpu-memory-utilization 0.85
  )
elif [[ "$VLLM_MODEL" == *"Phi-4"* ]] || [[ "$VLLM_MODEL" == *"phi-4"* ]]; then
  # Phi-4-reasoning-vision-15B: use BF16 (no fp8 quantization support)
  VLLM_EXTRA_ARGS=(--async-scheduling --gpu-memory-utilization 0.9)
  VLLM_TP="1"
  VLLM_GPUS="device=0"
elif [[ "$VLLM_MODEL" == *"Mistral-Small"* ]] || [[ "$VLLM_MODEL" == *"mistral-small"* ]]; then
  # Mistral Small 3.1 24B: vision model, ~55GB VRAM, use BF16
  VLLM_EXTRA_ARGS=(
    --limit-mm-per-prompt '{"image": 4, "video": 0}'
    --async-scheduling
    --gpu-memory-utilization 0.9
  )
  VLLM_TP="1"
  VLLM_GPUS="device=0"
elif [[ "$VLLM_MODEL" == *"gemma-3"* ]] || [[ "$VLLM_MODEL" == *"Gemma-3"* ]]; then
  # Gemma 3 12B: vision model, ~24GB VRAM, use BF16
  VLLM_EXTRA_ARGS=(
    --limit-mm-per-prompt '{"image": 4, "video": 0}'
    --async-scheduling
    --gpu-memory-utilization 0.9
  )
  VLLM_TP="1"
  VLLM_GPUS="device=0"
else
  VLLM_EXTRA_ARGS=(--quantization fp8 --async-scheduling --gpu-memory-utilization 0.9)
  VLLM_TP="1"
  VLLM_GPUS="device=0"
fi

# Create and run new container
echo "Starting local vLLM with $VLLM_MODEL (tensor-parallel-size=$VLLM_TP)..."
mkdir -p "$HF_CACHE"
if ! docker run -d \
  --name "$VLLM_CONTAINER_NAME" \
  --runtime nvidia \
  --gpus "$VLLM_GPUS" \
  --network host \
  -v "${HF_CACHE}:/root/.cache/huggingface" \
  --ipc=host \
  "$VLLM_IMAGE" \
  --model "$VLLM_MODEL" \
  --tensor-parallel-size "$VLLM_TP" \
  "${VLLM_EXTRA_ARGS[@]}" \
  --max-model-len 4096 \
  --trust-remote-code \
  --port "$VLLM_PORT"; then
  echo ""
  echo "$(red '✗') Failed to start vLLM container (see Docker error above)"
  return 1 2>/dev/null || exit 1
fi

# Helper to print container logs on failure
_print_vllm_logs() {
  echo ""
  echo "$(bold 'Container logs:')"
  echo "────────────────────────────────────────────────────────────────"
  docker logs "$VLLM_CONTAINER_NAME" 2>&1 | tail -50
  echo "────────────────────────────────────────────────────────────────"
  echo ""
}

# Wait for container to stay up (catch OOM) then for API to be ready
# 30B takes 5-10 min to load; 8B ~1 min; Phi-4 15B ~2-3 min
if [[ "$VLLM_MODEL" == *"30B"* ]]; then
  API_WAIT_MAX=120   # 10 min for 30B
  echo "Waiting for vLLM (30B model may take 5-10 min)..."
elif [[ "$VLLM_MODEL" == *"Phi-4"* ]] || [[ "$VLLM_MODEL" == *"phi-4"* ]]; then
  API_WAIT_MAX=48    # 4 min for Phi-4 15B
  echo "Waiting for vLLM (Phi-4 15B may take 2-3 min)..."
elif [[ "$VLLM_MODEL" == *"Mistral-Small"* ]] || [[ "$VLLM_MODEL" == *"mistral-small"* ]]; then
  API_WAIT_MAX=60    # 5 min for Mistral 24B
  echo "Waiting for vLLM (Mistral 24B may take 3-4 min)..."
elif [[ "$VLLM_MODEL" == *"gemma-3"* ]] || [[ "$VLLM_MODEL" == *"Gemma-3"* ]]; then
  API_WAIT_MAX=48    # 4 min for Gemma 3 12B
  echo "Waiting for vLLM (Gemma 3 12B may take 2-3 min)..."
else
  API_WAIT_MAX=36    # 3 min for 8B
  echo -n "Waiting for vLLM"
fi
for i in $(seq 1 "$API_WAIT_MAX"); do
  sleep 5
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$VLLM_CONTAINER_NAME"; then
    echo ""
    echo "$(red '✗') vLLM container exited (likely OOM, model load error, or unsupported args)"
    _print_vllm_logs
    if [[ "$VLLM_MODEL" == *"30B"* ]]; then
      echo "30B model needs multi-GPU. Set VLLM_TENSOR_PARALLEL_SIZE to your GPU count (e.g. 6)."
      echo "Or try the 8B model (option 1) for single-GPU."
    elif [[ "$VLLM_MODEL" == *"Phi-4"* ]] || [[ "$VLLM_MODEL" == *"phi-4"* ]]; then
      echo "Phi-4 15B needs ~30GB VRAM. Try the 8B model (option 1) if you have less."
    elif [[ "$VLLM_MODEL" == *"Mistral-Small"* ]] || [[ "$VLLM_MODEL" == *"mistral-small"* ]]; then
      echo "Mistral 24B needs ~55GB VRAM (e.g. 2x24GB or 1x80GB). Try the 8B model (option 1) if you have less."
    elif [[ "$VLLM_MODEL" == *"gemma-3"* ]] || [[ "$VLLM_MODEL" == *"Gemma-3"* ]]; then
      echo "Gemma 3 12B needs ~24GB VRAM. Try the 8B model (option 1) if you have less."
    else
      echo "Try the 8B model (option 1) if you have ~12GB VRAM."
    fi
    docker rm -f "$VLLM_CONTAINER_NAME" 2>/dev/null || true
    return 1 2>/dev/null || exit 1
  fi
  # Poll API - vLLM only listens after model is loaded
  if curl -sf --connect-timeout 3 "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
    echo ""
    break
  fi
  echo -n "."
  if [[ $i -eq "$API_WAIT_MAX" ]]; then
    echo ""
    echo "$(red '✗') API did not become ready in time"
    _print_vllm_logs
    echo "Model may still be loading. Check logs above for errors or run: docker logs $VLLM_CONTAINER_NAME -f"
    return 1 2>/dev/null || exit 1
  fi
done

echo "$(green '✓') Local vLLM ready on port $VLLM_PORT"
echo "  API: $(bold "http://localhost:${VLLM_PORT}/v1/chat/completions")"
export VLLM_LOCAL_URL="http://localhost:${VLLM_PORT}"
return 0 2>/dev/null || exit 0
