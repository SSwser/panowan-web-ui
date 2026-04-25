#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
export SERVICE_ROLE=worker
panowan_env_runtime

bash /app/scripts/check-runtime.sh
panowan_log_config
cd /app
exec python -m app.worker_service
