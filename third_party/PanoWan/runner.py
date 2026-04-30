"""PanoWan CLI/debug runner.

Per spec §9, CLI/debug execution and resident-host execution must share the
same backend-root validation and dispatch semantics. To enforce that, this
runner delegates execution to the resident provider's
``load_resident_runtime`` + ``run_job_inprocess`` instead of duplicating any
inference orchestration locally. The only responsibility unique to the CLI
path is parsing ``--job <json>`` and emitting the result JSON.
"""

import argparse
import json
import sys

from sources.runtime_adapter import (
    InvalidRunnerJob,
    runtime_identity_from_job,
    write_result,
)
from sources.runtime_provider import (
    load_resident_runtime,
    run_job_inprocess,
    teardown_resident_runtime,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args()


def _load_job(job_path: str) -> dict:
    with open(job_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = _parse_args()
    payload = _load_job(args.job)
    result_path = payload.get("result_path")
    loaded = None
    try:
        # Build identity from raw payload (validate happens inside the provider
        # to keep CLI/resident dispatch identical) — load_resident_runtime
        # itself does NOT validate the per-job payload, so we must rely on the
        # provider's run_job_inprocess for that contract enforcement.
        identity = runtime_identity_from_job(payload)
        loaded = load_resident_runtime(identity)
        result = run_job_inprocess(loaded, payload)
        write_result(result_path, result)
        return 0
    except InvalidRunnerJob as exc:
        write_result(
            result_path,
            {"status": "error", "code": "INVALID_INPUT", "message": str(exc)},
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 2
    except FileNotFoundError as exc:
        # Missing model weights or vendor tree — distinct from a payload bug.
        write_result(
            result_path,
            {"status": "error", "code": "RUNTIME_UNAVAILABLE", "message": str(exc)},
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 3
    finally:
        # CLI invocations are one-shot — release GPU resources before exit so
        # the next ``python runner.py`` does not race against the previous
        # process's CUDA cleanup. Resident execution skips this path.
        if loaded is not None:
            teardown_resident_runtime(loaded)


if __name__ == "__main__":
    raise SystemExit(main())
