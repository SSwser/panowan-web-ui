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

cd "${PANOWAN_ENGINE_DIR}"
log "Working directory: ${PANOWAN_ENGINE_DIR}"

# ── Dev mode: validate mounted source and sync Python environment ─────────────
if [[ "${DEV_MODE:-0}" == "1" ]]; then
    if [[ ! -f "pyproject.toml" ]]; then
        echo "ERROR: PanoWan source not found at ${PANOWAN_ENGINE_DIR}." >&2
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

# ── Model asset provisioning ──
log "Checking model assets..."
python -m app.models ensure

# Optional pagecache warm-up: set VMTOUCH_MODELS=1 in .env to enable.
# Pre-loads model weights into the OS page cache so the first inference
# doesn't pay the disk-read cost. Runs in the background to avoid delaying
# service startup.
if [[ "${VMTOUCH_MODELS:-0}" == "1" ]]; then
    if command -v vmtouch &>/dev/null; then
        log "Warming pagecache for model files (background)."
        vmtouch -t "${WAN_MODEL_PATH}" "$(dirname "${LORA_CHECKPOINT_PATH}")" &>/dev/null &
    else
        echo "WARNING: VMTOUCH_MODELS=1 but vmtouch is not installed, skipping."
    fi
fi

cd /app
panowan_log_config
log "Runtime prerequisites ready. Launching API service..."
exec python3 -m app.main