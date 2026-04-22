#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/env.sh"
panowan_env_host
panowan_env_tool_defaults

curl -fsS "${SERVICE_URL}/health"