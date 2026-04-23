#!/usr/bin/env bash
set -euo pipefail

value="${1:-}"

# Trim leading/trailing whitespace.
value="$(printf '%s' "${value}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

if [[ -z "${value}" ]]; then
    exit 0
fi

case "${value}" in
    /*|./*|../*|[A-Za-z]:*)
        printf '%s\n' "${value}"
        ;;
    *)
        printf './%s\n' "${value}"
        ;;
esac
