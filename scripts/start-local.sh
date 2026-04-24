#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

log() {
    printf '[startup][%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

run_timed() {
    local label="$1"
    shift
    local started_at="${SECONDS}"
    log "BEGIN: ${label}"
    "$@"
    local elapsed="$((SECONDS - started_at))"
    log "DONE : ${label} (${elapsed}s)"
}

cd "${PANOWAN_APP_DIR}"
log "Working directory: ${PANOWAN_APP_DIR}"

# ── Dev mode: validate mounted source and sync Python environment ─────────────
if [[ "${DEV_MODE:-0}" == "1" ]]; then
    if [[ ! -f "pyproject.toml" ]]; then
        echo "ERROR: PanoWan source not found at ${PANOWAN_APP_DIR}." >&2
        echo "Ensure third_party/PanoWan submodule is initialized (make init), then ensure pyproject.toml exists there." >&2
        exit 1
    fi
    if [[ -z "${UV_LINK_MODE:-}" ]]; then
        export UV_LINK_MODE=copy
        log "[dev] UV_LINK_MODE not set; defaulting to copy to avoid cross-filesystem hardlink warnings."
    fi
    log "[dev] Using shared uv cache at ${UV_CACHE_DIR:-/root/.cache/uv}"
    if [[ -f "uv.lock" ]]; then
        log "[dev] uv.lock detected. Running locked dependency sync."
        run_timed "uv sync --locked --link-mode=copy" uv sync --locked --link-mode=copy
    else
        log "[dev] uv.lock not found; running unlocked dependency sync."
        run_timed "uv sync --link-mode=copy" uv sync --link-mode=copy
    fi
fi

skip_model_download=false
if [[ "${DEV_MODE:-0}" == "1" ]] && [[ "${DEV_SKIP_DOWNLOAD_MODELS:-0}" == "1" ]]; then
    skip_model_download=true
    log "[dev] DEV_SKIP_DOWNLOAD_MODELS=1, skipping model and LoRA downloads."
fi

log "Checking model files in ${WAN_MODEL_PATH} and $(dirname "${LORA_CHECKPOINT_PATH}")"
if [[ "${skip_model_download}" != true ]] && ([[ ! -f "${WAN_DIFFUSION_FILE}" ]] || [[ ! -f "${WAN_T5_FILE}" ]]); then
    log "Wan model weights missing. Downloading into ${WAN_MODEL_PATH} (this can take several minutes)."
    export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
    mkdir -p "${WAN_MODEL_PATH}"
    run_timed "hf download Wan-AI/Wan2.1-T2V-1.3B" \
        uvx --from="huggingface_hub[cli]" hf download \
            Wan-AI/Wan2.1-T2V-1.3B \
            --local-dir "${WAN_MODEL_PATH}" \
            --max-workers "${HF_MAX_WORKERS:-8}"
else
    log "Wan model weights already present."
fi

lora_dir="$(dirname "${LORA_CHECKPOINT_PATH}")"

if [[ "${skip_model_download}" != true ]] && [[ ! -f "${LORA_CHECKPOINT_PATH}" ]]; then
    log "PanoWan LoRA checkpoint missing. Downloading into ${lora_dir}."
    mkdir -p "${lora_dir}"
    lora_downloaded=false
    for i in 1 2 3; do
        log "LoRA download attempt ${i}/3"
        if run_timed "download-panowan.sh attempt ${i}" bash ./scripts/download-panowan.sh "${lora_dir}"; then
            lora_downloaded=true
            break
        fi
        log "Attempt ${i} failed, waiting 30s before retry..."
        sleep 30
    done

    if [[ "${lora_downloaded}" != true ]]; then
        echo "Failed to download PanoWan LoRA weights after 3 attempts." >&2
        exit 1
    fi
else
    log "PanoWan LoRA checkpoint already present."
fi

# Optional pagecache warm-up: set VMTOUCH_MODELS=1 in .env to enable.
# Pre-loads model weights into the OS page cache so the first inference
# doesn't pay the disk-read cost. Runs in the background to avoid delaying
# service startup.
if [[ "${VMTOUCH_MODELS:-0}" == "1" ]]; then
    if command -v vmtouch &>/dev/null; then
        log "Warming pagecache for model files (background)."
        vmtouch -t "${WAN_MODEL_PATH}" "${lora_dir}" &>/dev/null &
    else
        echo "WARNING: VMTOUCH_MODELS=1 but vmtouch is not installed, skipping."
    fi
fi

cd /app
log "Runtime prerequisites ready. Launching API service..."
exec python3 -m app.main