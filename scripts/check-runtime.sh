#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

missing=0

require_path() {
  local path="$1"
  local label="$2"
  if [[ ! -e "${path}" ]]; then
    echo "ERROR: missing ${label}: ${path}" >&2
    missing=1
  fi
}

mkdir -p "${RUNTIME_DIR}" "${OUTPUT_DIR}"
if [[ ! -w "${RUNTIME_DIR}" ]]; then
  echo "ERROR: runtime directory is not writable: ${RUNTIME_DIR}" >&2
  missing=1
fi

require_path "${PANOWAN_ENGINE_DIR}" "PanoWan engine directory"
require_path "${WAN_DIFFUSION_FILE}" "Wan diffusion weights"
require_path "${WAN_T5_FILE}" "Wan T5 weights"
require_path "${LORA_CHECKPOINT_PATH}" "PanoWan LoRA checkpoint"

if [[ "${SERVICE_ROLE:-}" == "worker" ]]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi >/dev/null
  else
    echo "WARNING: nvidia-smi not found; relying on container runtime GPU injection." >&2
  fi
fi

if [[ "${missing}" != "0" ]]; then
  echo "Run: make setup-models" >&2
  exit 1
fi
