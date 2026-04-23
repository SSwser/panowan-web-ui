#!/usr/bin/env bash

panowan_env_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

panowan_env_load_dotenv() {
  local repo_root="$1"
  if [[ -f "${repo_root}/.env" ]]; then
    # shellcheck disable=SC1090
    set -a
    source "${repo_root}/.env"
    set +a
  fi
}

panowan_env_host() {
  local repo_root="${1:-$(panowan_env_repo_root)}"

  panowan_env_load_dotenv "${repo_root}"

  export REPO_ROOT="${REPO_ROOT:-${repo_root}}"
  export SERVICE_URL="${SERVICE_URL:-http://localhost:8000}"
  export MODEL_ROOT="${MODEL_ROOT:-${REPO_ROOT}/data/models}"
  export PANOWAN_SRC_DIR="${PANOWAN_SRC_DIR:-${REPO_ROOT}/third_party/PanoWan}"
  export PANOWAN_REPO_URL="${PANOWAN_REPO_URL:-https://github.com/VariantConst/PanoWan.git}"
  export WAN_MODEL_PATH="${WAN_MODEL_PATH:-${MODEL_ROOT}/Wan-AI/Wan2.1-T2V-1.3B}"
  export WAN_DIFFUSION_FILE="${WAN_DIFFUSION_FILE:-${WAN_MODEL_PATH}/diffusion_pytorch_model.safetensors}"
  export WAN_T5_FILE="${WAN_T5_FILE:-${WAN_MODEL_PATH}/models_t5_umt5-xxl-enc-bf16.pth}"
  export LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-${MODEL_ROOT}/PanoWan/latest-lora.ckpt}"
}

panowan_env_tool_defaults() {
  export SERVICE_URL="${SERVICE_URL:-http://localhost:8000}"
  export REQUEST_FILE="${REQUEST_FILE:-requests/generate-request.sample.json}"
  export OUTPUT_FILE="${OUTPUT_FILE:-output.mp4}"
  export POLL_INTERVAL="${POLL_INTERVAL:-5}"
  export PYTHON="${PYTHON:-python3}"
}

panowan_env_runtime() {
  export PANOWAN_DIR="${PANOWAN_DIR:-/app/PanoWan}"
  export WAN_MODEL_PATH="${WAN_MODEL_PATH:-./models/Wan-AI/Wan2.1-T2V-1.3B}"
  export WAN_DIFFUSION_FILE="${WAN_DIFFUSION_FILE:-${WAN_MODEL_PATH}/diffusion_pytorch_model.safetensors}"
  export WAN_T5_FILE="${WAN_T5_FILE:-${WAN_MODEL_PATH}/models_t5_umt5-xxl-enc-bf16.pth}"
  export LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-./models/PanoWan/latest-lora.ckpt}"
}