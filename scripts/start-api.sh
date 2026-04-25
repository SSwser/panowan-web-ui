#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

mkdir -p "${RUNTIME_DIR}" "${OUTPUT_DIR}"
panowan_log_config
cd /app
exec python -m app.api_service
