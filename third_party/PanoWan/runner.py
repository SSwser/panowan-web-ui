import argparse
import json
import sys
from pathlib import Path

from sources.runtime_adapter import InvalidRunnerJob, validate_job, write_result


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
    try:
        payload = validate_job(payload)
        # Phase 1 stub: backend-root contract surface only — actual model dispatch
        # lives in the resident runtime provider (Phase C). Touching the output keeps
        # downstream existence/size checks happy until vendor/ is wired up.
        output_path = payload["output_path"]
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).touch()
        write_result(result_path, {"status": "ok", "output_path": output_path})
        return 0
    except InvalidRunnerJob as exc:
        write_result(
            result_path,
            {"status": "error", "code": "INVALID_INPUT", "message": str(exc)},
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
