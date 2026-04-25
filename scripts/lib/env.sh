#!/usr/bin/env bash

panowan_env_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
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
  # Clone/cache path for host-side model setup scripts.
  # NOT the same as the git submodule at third_party/PanoWan used by dev compose —
  # keeping them separate avoids the submodule's .git file (vs directory) confusing
  # repo-detection logic, and lets prod scripts clone/cache independently.
  export PANOWAN_HOST_DIR="${PANOWAN_HOST_DIR:-${REPO_ROOT}/.cache/PanoWan}"
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

panowan_log_config() {
  local role="${SERVICE_ROLE:-unknown}"
  local banner="[config] role=${role}"
  banner="${banner} | runtime=${RUNTIME_DIR}"
  banner="${banner} | model_root=${MODEL_ROOT}"
  banner="${banner} | wan_model=${WAN_MODEL_PATH}"
  banner="${banner} | lora=${LORA_CHECKPOINT_PATH}"
  if [[ "${role}" == "worker" ]]; then
    banner="${banner} | engine=${PANOWAN_ENGINE_DIR}"
    banner="${banner} | gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'none/unavailable')"
    banner="${banner} | vmtouch=${VMTOUCH_MODELS:-0}"
    banner="${banner} | timeout=${GENERATION_TIMEOUT_SECONDS:-1800}s"
    banner="${banner} | max_concurrent=${MAX_CONCURRENT_JOBS:-1}"
  fi
  if [[ "${role}" == "api" ]]; then
    banner="${banner} | host=${HOST:-0.0.0.0}"
    banner="${banner} | port=${PORT:-8000}"
    banner="${banner} | job_store=${JOB_STORE_PATH}"
    banner="${banner} | dev_mode=${DEV_MODE:-0}"
  fi
  echo "${banner}"
}

panowan_env_runtime() {
  export SERVICE_ROLE="${SERVICE_ROLE:-api}"
  export RUNTIME_DIR="${RUNTIME_DIR:-/app/runtime}"
  export MODEL_ROOT="${MODEL_ROOT:-/models}"
  export PANOWAN_ENGINE_DIR="${PANOWAN_ENGINE_DIR:-/engines/panowan}"
  export WAN_MODEL_PATH="${WAN_MODEL_PATH:-${MODEL_ROOT}/Wan-AI/Wan2.1-T2V-1.3B}"
  export WAN_DIFFUSION_FILE="${WAN_DIFFUSION_FILE:-${WAN_MODEL_PATH}/diffusion_pytorch_model.safetensors}"
  export WAN_T5_FILE="${WAN_T5_FILE:-${WAN_MODEL_PATH}/models_t5_umt5-xxl-enc-bf16.pth}"
  export LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-${MODEL_ROOT}/PanoWan/latest-lora.ckpt}"
  export OUTPUT_DIR="${OUTPUT_DIR:-${RUNTIME_DIR}/outputs}"
  export JOB_STORE_PATH="${JOB_STORE_PATH:-${RUNTIME_DIR}/jobs.json}"
  export UPSCALE_ENGINE_DIR="${UPSCALE_ENGINE_DIR:-/engines/upscale}"
  # ADR 0003: backend weights live under model-family folders directly under
  # MODEL_ROOT (e.g. ${MODEL_ROOT}/Real-ESRGAN/...), not under a functional
  # upscale/ grouping. Default = MODEL_ROOT.
  export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}}"
  export UPSCALE_OUTPUT_DIR="${UPSCALE_OUTPUT_DIR:-${OUTPUT_DIR}}"
}