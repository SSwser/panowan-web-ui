#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
export SERVICE_ROLE=worker
panowan_env_runtime

bash /app/scripts/check-runtime.sh

# Optional pagecache warm-up: set VMTOUCH_MODELS=1 in .env to enable.
# Pre-loads model weights into the OS page cache so the first inference
# doesn't pay the disk-read cost. Runs in the background to avoid delaying
# service startup.
if [[ "${VMTOUCH_MODELS:-0}" == "1" ]]; then
    if command -v vmtouch &>/dev/null; then
        echo "[startup] Warming pagecache for model files (background)."
        vmtouch -t "${WAN_MODEL_PATH}" "$(dirname "${LORA_CHECKPOINT_PATH}")" &>/dev/null &
    else
        echo "[startup] WARNING: VMTOUCH_MODELS=1 but vmtouch is not installed, skipping."
    fi
fi

panowan_log_config
cd /app
exec python -m app.worker_service
