#!/usr/bin/env bash
set -euo pipefail

docker_proxy_export_wslenv_var() {
    local name="$1"
    if [[ -z "${!name:-}" ]]; then
        return
    fi

    if [[ -n "${WSLENV:-}" ]]; then
        case ":${WSLENV}:" in
            *":${name}:"*|*":${name}/"*) ;;
            *) export WSLENV="${WSLENV}:${name}" ;;
        esac
    else
        export WSLENV="${name}"
    fi
}

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
        if [[ "${wsl_cmd}" == "wsl.exe" ]]; then
            # Forward common compose interpolation variables into WSL so
            # `make`/shell overrides behave the same on Windows and WSL.
            for name in TAG MODEL_ROOT PORT APT_MIRROR PYPI_INDEX; do
                docker_proxy_export_wslenv_var "${name}"
            done
        fi
        exec "${wsl_cmd}" docker "$@"
    fi

done

echo "[docker-proxy] ERROR: docker not found locally or in WSL." >&2
echo "[docker-proxy] Fix options:" >&2
echo "  1) Install Docker Desktop (and enable WSL integration), or" >&2
echo "  2) Install Docker Engine inside WSL and ensure default distro works." >&2
exit 127
