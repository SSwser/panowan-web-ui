#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/env.sh"
panowan_env_host
panowan_env_tool_defaults

if [[ -n "${PROMPT:-}" ]]; then
  response="$(${PYTHON} -c 'import json,sys,urllib.request; req = urllib.request.Request(sys.argv[1] + "/generate", data=json.dumps({"prompt": sys.argv[2]}).encode(), headers={"Content-Type": "application/json"}, method="POST"); print(urllib.request.urlopen(req).read().decode())' "${SERVICE_URL}" "${PROMPT}")"
else
  response="$(${PYTHON} -c 'import pathlib,sys,urllib.request; payload = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"); req = urllib.request.Request(sys.argv[1] + "/generate", data=payload.encode(), headers={"Content-Type": "application/json"}, method="POST"); print(urllib.request.urlopen(req).read().decode())' "${SERVICE_URL}" "${REQUEST_FILE}")"
fi

echo "${response}"
job_id="$(printf '%s' "${response}" | ${PYTHON} -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"

while true; do
  status_json="$(curl -fsS "${SERVICE_URL}/jobs/${job_id}")"
  echo "${status_json}"
  status="$(printf '%s' "${status_json}" | ${PYTHON} -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  if [[ "${status}" == "completed" ]]; then
    curl -fsS "${SERVICE_URL}/jobs/${job_id}/download" -o "${OUTPUT_FILE}"
    echo "Saved ${OUTPUT_FILE}"
    break
  fi
  if [[ "${status}" == "failed" ]]; then
    echo "Job ${job_id} failed" >&2
    exit 1
  fi
  sleep "${POLL_INTERVAL}"
done