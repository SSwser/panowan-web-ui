#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

log() {
  printf '[model-setup][%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

mkdir -p "${WAN_MODEL_PATH}" "$(dirname "${LORA_CHECKPOINT_PATH}")" "${UPSCALE_MODEL_DIR}"

if [[ ! -f "${WAN_DIFFUSION_FILE}" ]] || [[ ! -f "${WAN_T5_FILE}" ]]; then
  log "Downloading Wan model weights into ${WAN_MODEL_PATH}"
  export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
  uvx --from="huggingface_hub[cli]" hf download \
    Wan-AI/Wan2.1-T2V-1.3B \
    --local-dir "${WAN_MODEL_PATH}" \
    --max-workers "${HF_MAX_WORKERS:-8}"
else
  log "Wan model weights already present."
fi

if [[ ! -f "${LORA_CHECKPOINT_PATH}" ]]; then
  log "Downloading PanoWan LoRA checkpoint into $(dirname "${LORA_CHECKPOINT_PATH}")"
  cd "${PANOWAN_ENGINE_DIR}"
  bash ./scripts/download-panowan.sh "$(dirname "${LORA_CHECKPOINT_PATH}")"
else
  log "PanoWan LoRA checkpoint already present."
fi

bash /app/scripts/check-runtime.sh
log "Model setup complete."
