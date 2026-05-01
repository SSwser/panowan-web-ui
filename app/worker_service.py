import logging
import os
import socket
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.backends.registry import discover
from app.cancellation import CallbackCancellationProbe, CancellationContext
from app.engines import EngineRegistry, PanoWanEngine, UpscaleEngine
from app.jobs import LocalJobBackend, LocalWorkerRegistry
from app.runtime_host import ResidentRuntimeHost, RuntimeState
from app.runtime_host_registration import build_provider_from_spec
from app.settings import settings
from app.upscaler import get_available_upscale_backends

logger = logging.getLogger(__name__)

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
    # Worker capability telemetry must reflect executable reality. When the
    # resident provider is absent, registering PanoWan would advertise generate
    # support even though the first job would fail at dispatch time.
    if host.has_provider("panowan"):
        registry.register(PanoWanEngine(host))
    registry.register(UpscaleEngine())
    return registry


def _resolve_engine(registry: EngineRegistry, job: dict):
    job_type = job.get("type", "generate")
    engine_name = JOB_TYPE_TO_ENGINE.get(job_type)
    if engine_name is None:
        raise ValueError(f"Unsupported job type: {job_type}")
    return registry.get(engine_name)


def _should_cancel_job(
    backend: LocalJobBackend, job_id: str, worker_id: str
) -> bool:
    """True when the engine should bail out of its current run.

    Engines must stop work either when cancellation has been requested
    (status ``cancelling``) or when this worker no longer owns the job at
    all (lease lost / job vanished). Both signal that any further engine
    output cannot legally land in a non-cancelled terminal state.
    """
    current = backend.get_job(job_id)
    if current is None:
        return True
    if current.get("worker_id") != worker_id:
        return True
    return current.get("status") not in {"claimed", "running"}


def _build_probe_for_job(
    backend: LocalJobBackend, job: dict, worker_id: str
) -> CallbackCancellationProbe:
    """Wrap the worker's stop-check with the job's cancel-governance metadata.

    The probe carries the same callable used historically by ``_should_cancel``
    plus the structured ``CancellationContext`` so providers can read mode and
    deadline at safe checkpoints without us threading extra kwargs through
    every layer.
    """
    job_id = str(job["job_id"])
    ctx = CancellationContext(
        job_id=job_id,
        worker_id=worker_id,
        mode=str(job.get("cancel_mode") or "soft"),
        requested_at=str(job.get("cancel_requested_at") or ""),
        deadline_at=str(job.get("cancel_deadline_at") or ""),
        attempt=int(job.get("cancel_attempt") or 0),
    )
    return CallbackCancellationProbe(
        context=ctx,
        stop_check=lambda: _should_cancel_job(backend, job_id, worker_id),
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


def log_transition(
    job_id: str,
    from_status: str,
    to_status: str,
    *,
    job_type: str,
    worker_id: str | None,
    reason: str,
) -> None:
    logger.info(
        "job_transition job_id=%s from_status=%s to_status=%s job_type=%s worker_id=%s reason=%s",
        job_id,
        from_status,
        to_status,
        job_type,
        worker_id or "-",
        reason,
    )


def log_worker_summary(
    backend: LocalJobBackend,
    registry: LocalWorkerRegistry,
    *,
    host: ResidentRuntimeHost,
    engine_registry: EngineRegistry,
) -> None:
    jobs = backend.list_jobs()
    workers = registry.list_workers(stale_seconds=settings.worker_stale_seconds)
    counts = Counter(str(job.get("status") or "unknown") for job in jobs)
    active_ids = [
        str(job.get("job_id"))
        for job in jobs
        if job.get("status") in {"claimed", "running", "cancelling"}
    ]
    logger.info(
        "worker_summary queued=%s claimed=%s running=%s cancelling=%s succeeded=%s failed=%s cancelled=%s online_workers=%s busy_workers=%s active_jobs=%s",
        counts.get("queued", 0),
        counts.get("claimed", 0),
        counts.get("running", 0),
        counts.get("cancelling", 0),
        counts.get("succeeded", 0),
        counts.get("failed", 0),
        counts.get("cancelled", 0),
        len(workers),
        sum(1 for w in workers if int(w.get("running_jobs") or 0) > 0),
        ",".join(active_ids) or "-",
    )


def run_one_job(
    backend: LocalJobBackend, registry: EngineRegistry, worker_id: str
) -> bool:
    job = backend.claim_next_job(worker_id=worker_id)
    if job is None:
        return False

    job_id = job["job_id"]
    job_type = job.get("type", "generate")
    started = backend.mark_running(job_id, worker_id)
    if started is None:
        # Cancellation or another writer raced ahead between claim and start;
        # release the polling tick without invoking the engine.
        log_transition(
            job_id,
            "claimed",
            "cancelled",
            job_type=job_type,
            worker_id=worker_id,
            reason="cancelled_before_start",
        )
        return True
    job = started

    engine = _resolve_engine(registry, job)

    probe = _build_probe_for_job(backend, job, worker_id)
    job = {
        **job,
        "_should_cancel": probe.should_stop,
        "_cancellation_probe": probe,
    }

    try:
        result = engine.run(job)
        # mark_succeeded refuses to overwrite a terminal state, so a cancel
        # observed while the engine was running stays cancelled instead of
        # being silently rewritten to succeeded by a late completion report.
        if backend.mark_succeeded(job_id, worker_id, result.output_path) is None:
            backend.request_cancellation(job_id, finished=True)
            log_transition(
                job_id,
                "running",
                "cancelled",
                job_type=job_type,
                worker_id=worker_id,
                reason="cancellation_observed_after_run",
            )
        else:
            log_transition(
                job_id,
                "running",
                "succeeded",
                job_type=job_type,
                worker_id=worker_id,
                reason="engine_completed",
            )
        return True
    except Exception as exc:
        # Engine failures are job-scoped; re-raising would terminate the
        # worker loop and leave the fleet idle until a manual restart.
        if backend.mark_failed(job_id, worker_id, str(exc)) is None:
            # Job was already moved to a terminal state (e.g., cancelled)
            # while the engine ran; leave the existing terminal record alone.
            log_transition(
                job_id,
                "running",
                "cancelled",
                job_type=job_type,
                worker_id=worker_id,
                reason="cancellation_observed_during_failure",
            )
        else:
            log_transition(
                job_id,
                "running",
                "failed",
                job_type=job_type,
                worker_id=worker_id,
                reason="engine_exception",
            )
        return True


def reconcile_overdue_cancellations(
    backend: LocalJobBackend,
    *,
    worker_id: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Force jobs whose cancel deadline has elapsed into terminal ``failed``.

    Owned by the worker loop: cancellation convergence is a worker-side
    responsibility per ADR 0010, so the API never needs to police deadlines.
    """
    now = now or datetime.now(UTC)
    reconciled: list[dict[str, object]] = []
    for job in backend.list_jobs():
        if job.get("status") != "cancelling":
            continue
        if worker_id is not None and job.get("worker_id") != worker_id:
            continue
        deadline_raw = job.get("cancel_deadline_at")
        if not deadline_raw:
            continue
        try:
            deadline_at = datetime.fromisoformat(str(deadline_raw))
        except ValueError:
            continue
        if deadline_at > now:
            continue
        result = backend.finalize_cancellation_timeout(
            str(job["job_id"]),
            worker_id=str(job["worker_id"]),
            reason="cancel_timeout",
        )
        if result is not None:
            reconciled.append(result)
    return reconciled


def finalize_runtime_cancellation(
    backend: LocalJobBackend,
    worker_registry: LocalWorkerRegistry,
    *,
    job_id: str,
    worker_id: str,
) -> dict[str, object] | None:
    """Confirm cooperative cancellation and release the worker's occupancy.

    Routing the running-jobs decrement through the worker registry here
    keeps occupancy accounting co-located with the cancellation outcome,
    so the next telemetry tick cannot observe a phantom in-flight slot.
    """
    result = backend.request_cancellation(job_id, worker_id=worker_id, finished=True)
    if result is not None:
        worker_registry.set_running_jobs(worker_id, 0)
    return result


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
        log_worker_summary(
            backend, worker_registry, host=host, engine_registry=registry
        )
        _maybe_evict_idle(host)
        worked = run_one_job(backend, registry, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
