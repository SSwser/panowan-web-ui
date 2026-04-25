import os
import socket
import time

from app.engines import EngineRegistry, PanoWanEngine, UpscaleEngine
from app.jobs import LocalJobBackend
from app.settings import settings


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
        if _worker_still_owns_job(backend, job_id, worker_id):
            backend.complete_job(job_id, result.output_path)
        return True
    except Exception as exc:
        if _worker_still_owns_job(backend, job_id, worker_id):
            backend.fail_job(job_id, str(exc))
            raise
        return True


def main() -> None:
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    backend = LocalJobBackend(settings.job_store_path)
    registry = build_registry()

    for engine in registry.all():
        engine.validate_runtime()

    caps = []
    for engine in registry.all():
        caps.extend(engine.capabilities)

    print(
        f"Worker started: id={worker_id} capabilities={','.join(caps)}",
        flush=True,
    )
    while True:
        worked = run_one_job(backend, registry, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
