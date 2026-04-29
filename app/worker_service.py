import os
import socket
import time

from app.engines import EngineRegistry, PanoWanEngine, UpscaleEngine
from app.jobs import LocalJobBackend, LocalWorkerRegistry
from app.settings import settings
from app.upscaler import get_available_upscale_backends


JOB_TYPE_TO_ENGINE = {
    "generate": "panowan",
    "upscale": "upscale",
}


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PanoWanEngine())
    registry.register(UpscaleEngine())
    return registry


def _resolve_engine(registry: EngineRegistry, job: dict):
    job_type = job.get("type", "generate")
    engine_name = JOB_TYPE_TO_ENGINE.get(job_type)
    if engine_name is None:
        raise ValueError(f"Unsupported job type: {job_type}")
    return registry.get(engine_name)


def _worker_still_owns_job(
    backend: LocalJobBackend, job_id: str, worker_id: str
) -> bool:
    current = backend.get_job(job_id)
    return bool(
        current is not None
        and current.get("status") == "running"
        and current.get("worker_id") == worker_id
    )


def publish_worker_state(
    registry: LocalWorkerRegistry,
    worker_id: str,
    engine_registry: EngineRegistry,
    running_jobs: int = 0,
) -> dict:
    caps = []
    for engine in engine_registry.all():
        caps.extend(engine.capabilities)
    available_upscale_models = sorted(
        get_available_upscale_backends(
            settings.upscale_engine_dir,
            settings.upscale_weights_dir,
        ).keys()
    )
    return registry.upsert_worker(
        worker_id,
        {
            "status": "online",
            "capabilities": sorted(set(caps)),
            "available_upscale_models": available_upscale_models,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            "running_jobs": running_jobs,
        },
    )


def run_one_job(
    backend: LocalJobBackend, registry: EngineRegistry, worker_id: str
) -> bool:
    job = backend.claim_next_job(worker_id=worker_id)
    if job is None:
        return False

    if not _worker_still_owns_job(backend, job["job_id"], worker_id):
        return True

    engine = _resolve_engine(registry, job)

    job_id = job["job_id"]
    job = {
        **job,
        "_should_cancel": lambda: not _worker_still_owns_job(
            backend, job_id, worker_id
        ),
    }

    try:
        result = engine.run(job)
        backend.complete_job_if_running(job_id, worker_id, result.output_path)
        return True
    except Exception as exc:
        # Upscale and generation failures are job-scoped errors. Re-raising here
        # would terminate the worker loop and leave the fleet unavailable until
        # someone manually restarts the process.
        backend.fail_job_if_running(job_id, worker_id, str(exc))
        return True


def main() -> None:
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    backend = LocalJobBackend(settings.job_store_path)
    worker_registry = LocalWorkerRegistry(settings.worker_store_path)
    registry = build_registry()

    for engine in registry.all():
        engine.validate_runtime()

    worker_state = publish_worker_state(worker_registry, worker_id, registry)
    caps = worker_state["capabilities"]
    upscale_models = worker_state["available_upscale_models"]

    print(
        f"Worker started: id={worker_id} capabilities={','.join(caps)} "
        f"upscale_models={','.join(upscale_models) or 'none'}",
        flush=True,
    )
    while True:
        publish_worker_state(worker_registry, worker_id, registry)
        worked = run_one_job(backend, registry, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
