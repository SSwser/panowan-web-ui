#!/usr/bin/env bash
set -euo pipefail

MODEL_ROOT="$(realpath "${MODEL_ROOT:-data/models}")"
PANOWAN_SRC_DIR="${PANOWAN_SRC_DIR:-.cache/PanoWan}"
PANOWAN_REPO_URL="${PANOWAN_REPO_URL:-https://github.com/VariantConst/PanoWan.git}"
WAN_MODEL_PATH="${WAN_MODEL_PATH:-${MODEL_ROOT}/Wan-AI/Wan2.1-T2V-1.3B}"
LORA_DIR="${LORA_DIR:-${MODEL_ROOT}/PanoWan}"

if [[ ! -d "${PANOWAN_SRC_DIR}/.git" ]]; then
    mkdir -p "$(dirname "${PANOWAN_SRC_DIR}")"
    git clone "${PANOWAN_REPO_URL}" "${PANOWAN_SRC_DIR}"
fi

cd "${PANOWAN_SRC_DIR}"

if [[ ! -f "${WAN_MODEL_PATH}/diffusion_pytorch_model.safetensors" ]] || \
   [[ ! -f "${WAN_MODEL_PATH}/models_t5_umt5-xxl-enc-bf16.pth" ]]; then
    mkdir -p "${WAN_MODEL_PATH}"
    echo "Downloading Wan model weights into ${WAN_MODEL_PATH}..."
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
    uvx --from="huggingface_hub[cli]" hf download \
        Wan-AI/Wan2.1-T2V-1.3B \
        --local-dir "${WAN_MODEL_PATH}" \
        --max-workers "${HF_MAX_WORKERS:-8}"
fi

if [[ ! -f "${LORA_DIR}/latest-lora.ckpt" ]]; then
    mkdir -p "${LORA_DIR}"
    echo "Downloading PanoWan LoRA weights into ${LORA_DIR}..."
    bash ./scripts/download-panowan.sh "${LORA_DIR}"
fi

echo "Model prefetch complete: ${MODEL_ROOT}"