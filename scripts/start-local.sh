#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

cd "${PANOWAN_APP_DIR}"

# ── Dev mode: validate mounted source and sync Python environment ─────────────
if [[ "${DEV_MODE:-0}" == "1" ]]; then
    if [[ ! -f "pyproject.toml" ]]; then
        echo "ERROR: PanoWan source not found at ${PANOWAN_APP_DIR}." >&2
        echo "Ensure third_party/PanoWan submodule is initialized (make init), then ensure pyproject.toml exists there." >&2
        exit 1
    fi
    echo "[dev] Using shared uv cache at ${UV_CACHE_DIR:-/root/.cache/uv}"
    if [[ -f "uv.lock" ]]; then
        echo "[dev] Syncing PanoWan dependencies (uv sync --locked)..."
        uv sync --locked
    else
        echo "[dev] uv.lock not found; running uv sync without --locked."
        uv sync
    fi
fi

skip_model_download=false
if [[ "${DEV_MODE:-0}" == "1" ]] && [[ "${DEV_SKIP_DOWNLOAD_MODELS:-0}" == "1" ]]; then
    skip_model_download=true
    echo "[dev] DEV_SKIP_DOWNLOAD_MODELS=1, skipping model and LoRA downloads."
fi

if [[ "${skip_model_download}" != true ]] && ([[ ! -f "${WAN_DIFFUSION_FILE}" ]] || [[ ! -f "${WAN_T5_FILE}" ]]); then
    echo "Downloading Wan model weights into ${WAN_MODEL_PATH}..."
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
    mkdir -p "${WAN_MODEL_PATH}"
    uvx --from="huggingface_hub[cli]" hf download \
        Wan-AI/Wan2.1-T2V-1.3B \
        --local-dir "${WAN_MODEL_PATH}" \
        --max-workers "${HF_MAX_WORKERS:-8}"
fi

lora_dir="$(dirname "${LORA_CHECKPOINT_PATH}")"

if [[ "${skip_model_download}" != true ]] && [[ ! -f "${LORA_CHECKPOINT_PATH}" ]]; then
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

# Optional pagecache warm-up: set VMTOUCH_MODELS=1 in .env to enable.
# Pre-loads model weights into the OS page cache so the first inference
# doesn't pay the disk-read cost. Runs in the background to avoid delaying
# service startup.
if [[ "${VMTOUCH_MODELS:-0}" == "1" ]]; then
    if command -v vmtouch &>/dev/null; then
        echo "Warming pagecache for model files (background)..."
        vmtouch -t "${WAN_MODEL_PATH}" "${lora_dir}" &>/dev/null &
    else
        echo "WARNING: VMTOUCH_MODELS=1 but vmtouch is not installed, skipping."
    fi
fi

cd /app
exec python3 -m app.main