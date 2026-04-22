#!/usr/bin/env bash
set -euo pipefail

PANOWAN_DIR="${PANOWAN_DIR:-/app/PanoWan}"
WAN_MODEL_PATH="${WAN_MODEL_PATH:-./models/Wan-AI/Wan2.1-T2V-1.3B}"
LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-./models/PanoWan/latest-lora.ckpt}"

cd "${PANOWAN_DIR}"

if [[ ! -d "${WAN_MODEL_PATH}" ]] || [[ ! -f "${WAN_MODEL_PATH}/models_t5_umt5-xxl-enc-bf16.pth" ]]; then
    echo "Downloading Wan model weights into ${WAN_MODEL_PATH}..."
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
    mkdir -p "${WAN_MODEL_PATH}"
    uvx --from="huggingface_hub[cli]" hf download \
        Wan-AI/Wan2.1-T2V-1.3B \
        --local-dir "${WAN_MODEL_PATH}" \
        --max-workers "${HF_MAX_WORKERS:-8}"
fi

lora_dir="$(dirname "${LORA_CHECKPOINT_PATH}")"
lora_file="${LORA_CHECKPOINT_PATH#./}"

if [[ ! -f "${lora_file}" ]]; then
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