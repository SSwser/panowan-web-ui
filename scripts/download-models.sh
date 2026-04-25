#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_host

export UPSCALE_ENGINE_DIR="${UPSCALE_ENGINE_DIR:-${REPO_ROOT}/third_party/Upscale}"
export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}/upscale}"
export PANOWAN_ENGINE_DIR="${PANOWAN_ENGINE_DIR:-${REPO_ROOT}/third_party/PanoWan}"

exec python -m app.models ensure