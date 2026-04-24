#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_host

LORA_DIR="$(dirname "${LORA_CHECKPOINT_PATH}")"

if [[ ! -d "${PANOWAN_HOST_DIR}/.git" ]]; then
    mkdir -p "$(dirname "${PANOWAN_HOST_DIR}")"
    git clone "${PANOWAN_REPO_URL}" "${PANOWAN_HOST_DIR}"
fi

cd "${PANOWAN_HOST_DIR}"

if [[ ! -f "${WAN_DIFFUSION_FILE}" ]] || [[ ! -f "${WAN_T5_FILE}" ]]; then
    mkdir -p "${WAN_MODEL_PATH}"
    echo "Downloading Wan model weights into ${WAN_MODEL_PATH}..."
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
    uvx --from="huggingface_hub[cli]" hf download \
        Wan-AI/Wan2.1-T2V-1.3B \
        --local-dir "${WAN_MODEL_PATH}" \
        --max-workers "${HF_MAX_WORKERS:-8}"
fi

if [[ ! -f "${LORA_CHECKPOINT_PATH}" ]]; then
    mkdir -p "${LORA_DIR}"
    echo "Downloading PanoWan LoRA weights into ${LORA_DIR}..."
    bash ./scripts/download-panowan.sh "${LORA_DIR}"
fi

echo "Host model download complete: ${MODEL_ROOT}. Use 'make setup-models' (compose model-setup role) for the production runtime layout."