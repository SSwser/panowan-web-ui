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

panowan_export_python_settings() {
  local repo_root="$1"
  PYTHONPATH="${repo_root}${PYTHONPATH:+:${PYTHONPATH}}" "${PYTHON:-python3}" - <<'PY'
import shlex

from app.settings import load_settings

settings = load_settings()
exports = {
    "MODEL_ROOT": settings.model_root,
    "RUNTIME_DIR": settings.runtime_dir,
    "PANOWAN_ENGINE_DIR": settings.panowan_engine_dir,
    "WAN_MODEL_PATH": settings.wan_model_path,
    "WAN_DIFFUSION_FILE": settings.wan_diffusion_absolute_path,
    "WAN_T5_FILE": settings.wan_t5_absolute_path,
    "LORA_CHECKPOINT_PATH": settings.lora_checkpoint_path,
    "OUTPUT_DIR": settings.output_dir,
    "JOB_STORE_PATH": settings.job_store_path,
    "WORKER_STORE_PATH": settings.worker_store_path,
    "UPSCALE_ENGINE_DIR": settings.upscale_engine_dir,
    "UPSCALE_WEIGHTS_DIR": settings.upscale_weights_dir,
    "UPSCALE_OUTPUT_DIR": settings.upscale_output_dir,
    "UPSCALE_TIMEOUT_SECONDS": str(settings.upscale_timeout_seconds),
    "WORKER_STALE_SECONDS": str(settings.worker_stale_seconds),
}
for key, value in exports.items():
    print(f"export {key}={shlex.quote(value)}")
PY
}

panowan_env_host() {
  local repo_root="${1:-$(panowan_env_repo_root)}"

  panowan_env_load_dotenv "${repo_root}"

  export REPO_ROOT="${REPO_ROOT:-${repo_root}}"
  export SERVICE_URL="${SERVICE_URL:-http://localhost:8000}"
  eval "$(panowan_export_python_settings "${repo_root}")"
  # Clone/cache path for host-side model setup scripts.
  # NOT the same as the git submodule at third_party/PanoWan used by dev compose —
  # keeping them separate avoids the submodule's .git file (vs directory) confusing
  # repo-detection logic, and lets prod scripts clone/cache independently.
  export PANOWAN_HOST_DIR="${PANOWAN_HOST_DIR:-${REPO_ROOT}/.cache/PanoWan}"
  export PANOWAN_REPO_URL="${PANOWAN_REPO_URL:-https://github.com/VariantConst/PanoWan.git}"
}

panowan_env_tool_defaults() {
  export SERVICE_URL="${SERVICE_URL:-http://localhost:8000}"
  export REQUEST_FILE="${REQUEST_FILE:-requests/generate-request.sample.json}"
  export OUTPUT_FILE="${OUTPUT_FILE:-output.mp4}"
  export POLL_INTERVAL="${POLL_INTERVAL:-5}"
  export PYTHON="${PYTHON:-python3}"
}

panowan_log_option() {
  printf '[Options]  %-12s = %s\n' "$1" "${2:-}"
}

panowan_log_group() {
  echo "[Options]"
  echo "[Options]  ─── $1 ─────────────────────────────────────────"
}

panowan_log_section() {
  local group="$1"
  shift
  panowan_log_group "$group"
  for item in "$@"; do
    local label="${item%%:*}"
    local var="${item#*:}"
    panowan_log_option "$label" "${!var}"
  done
}

panowan_log_config() {
  local service_role="${SERVICE_ROLE:-unknown}"
  local runtime="${RUNTIME_DIR}"
  local model_root="${MODEL_ROOT}"
  local wan_model="${WAN_MODEL_PATH}"
  local lora="${LORA_CHECKPOINT_PATH}"
  local upscale_dir="${UPSCALE_ENGINE_DIR}"
  local upscale_wt="${UPSCALE_WEIGHTS_DIR}"
  local upscale_out="${UPSCALE_OUTPUT_DIR}"
  local worker_db="${WORKER_STORE_PATH}"
  local engine="${PANOWAN_ENGINE_DIR}"
  local output_dir="${OUTPUT_DIR}"
  local gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'none/unavailable')"
  local vmtouch="${VMTOUCH_MODELS:-0}"
  local timeout="${GENERATION_TIMEOUT_SECONDS:-1800}s"
  local ups_timeout="${UPSCALE_TIMEOUT_SECONDS:-1800}s"
  local max_concurrent="${MAX_CONCURRENT_JOBS:-1}"
  local host="${HOST:-0.0.0.0}"
  local port="${PORT:-8000}"
  local job_store="${JOB_STORE_PATH}"
  local stale_sec="${WORKER_STALE_SECONDS:-60}"
  local dev_mode="${DEV_MODE:-0}"

  echo "[Options] ────────────────────────────────────────────"

  panowan_log_section "Common" \
    role:service_role \
    runtime:runtime \
    model_root:model_root \
    worker_db:worker_db

  panowan_log_section "Model" \
    wan_model:wan_model \
    lora:lora \
    upscale_dir:upscale_dir \
    upscale_wt:upscale_wt \
    upscale_out:upscale_out

  if [[ "${service_role}" == "worker" ]]; then
    panowan_log_section "Worker" \
      engine:engine \
      gpu:gpu \
      output_dir:output_dir \
      vmtouch:vmtouch \
      timeout:timeout \
      ups_timeout:ups_timeout \
      max_concurrent:max_concurrent
  elif [[ "${service_role}" == "api" ]]; then
    panowan_log_section "API" \
      host:host \
      port:port \
      job_store:job_store \
      stale_sec:stale_sec \
      dev_mode:dev_mode
  fi

  echo "[Options] ────────────────────────────────────────────"
}

panowan_env_runtime() {
  local repo_root="${1:-/app}"
  export SERVICE_ROLE="${SERVICE_ROLE:-api}"
  eval "$(panowan_export_python_settings "${repo_root}")"
}