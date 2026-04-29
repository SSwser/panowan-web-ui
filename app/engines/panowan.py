import os

from app.generator import build_runner_payload
from app.settings import settings
from app.worker_runtime import PanoWanRuntimeController
from third_party.PanoWan.sources.runtime_adapter import (
    classify_runtime_failure,
    runtime_identity_from_job,
)

from .base import EngineResult


def _load_pipeline(identity):
    # Phase 1 stub: no actual model loading until vendor/ is populated.
    # Phase 2 (Phase C) replaces this with importlib-based vendor/ dispatch.
    return {"identity": identity}


def _teardown_pipeline(pipeline):
    pipeline.clear()


def _execute_job(pipeline, job):
    # Phase 1 stub: just return the output_path from the job payload.
    # Phase 2 (Phase C) replaces this with actual pipeline.run() via vendor/ dispatch.
    output_path = job.get("output_path", "")
    return {"status": "ok", "output_path": output_path}


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v")

    def __init__(self) -> None:
        self._controller = PanoWanRuntimeController(
            load_fn=_load_pipeline,
            teardown_fn=_teardown_pipeline,
        )

    def validate_runtime(self) -> None:
        missing = []
        runner_path = os.path.join(settings.panowan_engine_dir, "runner.py")
        for path in (
            runner_path,
            settings.wan_diffusion_absolute_path,
            settings.wan_t5_absolute_path,
            settings.lora_absolute_path,
        ):
            if not os.path.exists(path):
                missing.append(path)
        if missing:
            joined = "\n".join(f"- {path}" for path in missing)
            raise FileNotFoundError(
                "PanoWan runtime assets are missing. Run `make setup-backends` first.\n"
                "Missing: runner.py means the backend root was not installed.\n"
                f"{joined}"
            )

    def run(self, job: dict) -> EngineResult:
        runner_payload = build_runner_payload(job)
        identity = runtime_identity_from_job(runner_payload)
        result = self._controller.run_job(
            runner_payload,
            identity=identity,
            execute_fn=_execute_job,
            is_runtime_corrupting=classify_runtime_failure,
        )
        return EngineResult(output_path=result["output_path"], metadata={})

    def evict_runtime(self) -> None:
        """Tear down the resident pipeline (called by worker loop on idle eviction)."""
        self._controller.evict()
