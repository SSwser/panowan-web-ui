#!/usr/bin/env bash
set -euo pipefail

# Prefer local docker first.
if command -v docker >/dev/null 2>&1; then
    exec docker "$@"
fi

# Fallback to docker inside WSL when running on Windows without docker CLI.
for wsl_cmd in wsl.exe wsl; do
    if ! command -v "${wsl_cmd}" >/dev/null 2>&1; then
        continue
    fi

    if "${wsl_cmd}" sh -lc 'command -v docker >/dev/null 2>&1'; then
        echo "[docker-proxy] local docker not found, using WSL docker via ${wsl_cmd}" >&2
        exec "${wsl_cmd}" docker "$@"
    fi

done

echo "[docker-proxy] ERROR: docker not found locally or in WSL." >&2
echo "[docker-proxy] Fix options:" >&2
echo "  1) Install Docker Desktop (and enable WSL integration), or" >&2
echo "  2) Install Docker Engine inside WSL and ensure default distro works." >&2
exit 127
