import os
import socket
import time
from pathlib import Path

from app.backends.registry import discover
from app.engines import EngineRegistry, PanoWanEngine, UpscaleEngine
from app.jobs import LocalJobBackend, LocalWorkerRegistry
from app.runtime_host import ResidentRuntimeHost, RuntimeState
from app.runtime_host_registration import build_provider_from_spec
from app.settings import settings
from app.upscaler import get_available_upscale_backends

JOB_TYPE_TO_ENGINE = {
    "generate": "panowan",
    "upscale": "upscale",
}

# Map RuntimeState enum to the legacy string values previously emitted by
# PanoWanRuntimeController.status_snapshot()["status"]. The worker registry
# telemetry contract (panowan_runtime_status field) is consumed by the API/UI
# and must stay stable.
_RUNTIME_STATE_TO_STATUS = {
    RuntimeState.COLD: "cold",
    RuntimeState.LOADING: "loading",
    RuntimeState.WARM: "warm",
    RuntimeState.RUNNING: "running",
    RuntimeState.EVICTING: "evicting",
    RuntimeState.FAILED: "failed",
}


def _backend_discovery_root() -> Path:
    # The third_party root is the parent of the panowan backend directory.
    # Discovery walks every backend.toml at depth 1, matching the path used by
    # app.upscaler and app.backends.model_specs.
    return Path(settings.panowan_engine_dir).parent


def build_host() -> ResidentRuntimeHost:
    """Build the platform-owned ResidentRuntimeHost with all enabled providers."""
    host = ResidentRuntimeHost()
    root = _backend_discovery_root()
    if not root.exists():
        return host
    for spec in discover(root):
        if not spec.resident_provider.enabled:
            continue
        provider = build_provider_from_spec(
            spec.resident_provider, backend_root=spec.root
        )
        host.register_provider(provider)
    return host


def build_registry(host: ResidentRuntimeHost) -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PanoWanEngine(host))
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
    host: ResidentRuntimeHost,
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
            "panowan_runtime_status": _resident_runtime_status(host),
        },
    )


def _resident_runtime_status(host: ResidentRuntimeHost) -> str:
    """Map the host's panowan provider snapshot to the legacy status string.

    Returns "unknown" when no panowan provider is registered so the worker
    telemetry contract stays stable when the backend is missing.
    """
    snapshot = host.status("panowan")
    if snapshot is None:
        return "unknown"
    return _RUNTIME_STATE_TO_STATUS.get(snapshot.state, snapshot.state.value)


def _startup_preload(host: ResidentRuntimeHost) -> None:
    if not settings.panowan_startup_preload:
        return
    if not host.has_provider("panowan"):
        return
    try:
        host.preload("panowan")
        print("PanoWan runtime preloaded.", flush=True)
    # Preload is best-effort; worker must keep running even if model load fails.
    except Exception as exc:
        print(f"PanoWan startup preload failed (non-fatal): {exc}", flush=True)


def _maybe_evict_idle(host: ResidentRuntimeHost) -> None:
    """Evict the PanoWan resident runtime if idle past the configured threshold."""
    if settings.panowan_idle_evict_seconds <= 0:
        return
    if not host.has_provider("panowan"):
        return
    if host.maybe_evict_idle("panowan", settings.panowan_idle_evict_seconds):
        print(
            "PanoWan runtime evicted after >= "
            f"{settings.panowan_idle_evict_seconds:.0f}s idle.",
            flush=True,
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
    host = build_host()
    registry = build_registry(host)

    for engine in registry.all():
        engine.validate_runtime()

    worker_state = publish_worker_state(worker_registry, worker_id, registry, host)
    caps = worker_state["capabilities"]
    upscale_models = worker_state["available_upscale_models"]

    print(
        f"Worker started: id={worker_id} capabilities={','.join(caps)} "
        f"upscale_models={','.join(upscale_models) or 'none'}",
        flush=True,
    )
    _startup_preload(host)
    while True:
        publish_worker_state(worker_registry, worker_id, registry, host)
        _maybe_evict_idle(host)
        worked = run_one_job(backend, registry, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
