#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

cd "${PANOWAN_DIR}"

if [[ ! -f "${WAN_DIFFUSION_FILE}" ]] || [[ ! -f "${WAN_T5_FILE}" ]]; then
    echo "Downloading Wan model weights into ${WAN_MODEL_PATH}..."
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
    mkdir -p "${WAN_MODEL_PATH}"
    uvx --from="huggingface_hub[cli]" hf download \
        Wan-AI/Wan2.1-T2V-1.3B \
        --local-dir "${WAN_MODEL_PATH}" \
        --max-workers "${HF_MAX_WORKERS:-8}"
fi

lora_dir="$(dirname "${LORA_CHECKPOINT_PATH}")"

if [[ ! -f "${LORA_CHECKPOINT_PATH}" ]]; then
    echo "Downloading PanoWan LoRA weights into ${lora_dir}..."
    mkdir -p "${lora_dir}"
    lora_downloaded=false
    for i in 1 2 3; do
        if bash ./scripts/download-panowan.sh "${lora_dir}"; then
            lora_downloaded=true
            break
        fi
        echo "Attempt ${i} failed, waiting 30s..."
        sleep 30
    done

    if [[ "${lora_downloaded}" != true ]]; then
        echo "Failed to download PanoWan LoRA weights after 3 attempts." >&2
        exit 1
    fi
fi

cd /app
exec python3 -m app.main