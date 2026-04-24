import os
import socket
import time

from app.engines import EngineRegistry, PanoWanEngine
from app.jobs import LocalJobBackend
from app.settings import settings


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PanoWanEngine())
    return registry


def run_one_job(backend: LocalJobBackend, engine, worker_id: str) -> bool:
    job = backend.claim_next_job(worker_id=worker_id)
    if job is None:
        return False
    try:
        result = engine.run(job)
        backend.complete_job(job["job_id"], result.output_path)
        return True
    except Exception as exc:
        backend.fail_job(job["job_id"], str(exc))
        raise


def main() -> None:
    engine_name = os.getenv("ENGINE", "panowan")
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    backend = LocalJobBackend(settings.job_store_path)
    engine = build_registry().get(engine_name)
    engine.validate_runtime()

    print(
        f"Worker started: id={worker_id} engine={engine.name} capabilities={','.join(engine.capabilities)}",
        flush=True,
    )
    while True:
        worked = run_one_job(backend, engine, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
