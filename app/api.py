import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from .generator import extract_prompt, resolve_inference_params
from .jobs import LocalJobBackend, LocalWorkerRegistry, now_iso
from .result_views import (
    build_result_summaries,
    build_result_summary,
    result_id_for_root_job,
    version_id_for_job,
)
from .settings import settings
from .sse import broadcast_job_event, subscribe, unsubscribe
from .upscaler import UPSCALE_BACKENDS
from .worker_service import reconcile_overdue_cancellations


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        backend = get_job_backend()
        backend.restore()
        # A restarted API has lost the in-flight runtime context, so restored
        # cancelling jobs cannot keep waiting for a worker-side convergence that
        # may never happen.
        reconcile_overdue_cancellations(
            backend,
            now=_far_future_utc(),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not restore jobs from disk: {exc}", flush=True)
    yield


def _far_future_utc() -> datetime:
    return datetime.max.replace(tzinfo=UTC)


app = FastAPI(
    title=settings.service_title,
    description="Run PanoWan video generation inside a local Docker container.",
    version=settings.service_version,
    lifespan=lifespan,
)


class _HealthCheckAccessFilter(logging.Filter):
    """Suppress successful health probe access log lines from uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return '"GET /health HTTP/1.1" 200' not in msg


def _configure_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(flt, _HealthCheckAccessFilter) for flt in logger.filters):
        return
    logger.addFilter(_HealthCheckAccessFilter())


_configure_access_log_filter()


_job_backend: LocalJobBackend | None = None
_worker_registry: LocalWorkerRegistry | None = None
_JOB_EVENT_FIELDS = (
    "job_id",
    "status",
    "type",
    "prompt",
    "params",
    "output_path",
    "created_at",
    "started_at",
    "finished_at",
    "error",
    "source_job_id",
    "upscale_params",
    "source_output_path",
    "worker_id",
    "download_url",
    "cancel_mode",
    "cancel_attempt",
    "cancel_requested_at",
    "cancel_deadline_at",
)


def _sse_event(event: str, payload: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


def get_job_backend() -> LocalJobBackend:
    """Return a process-cached ``LocalJobBackend`` for the active store path.

    We cache by ``job_store_path`` so tests that patch ``settings`` to per-test
    tmpdirs still get isolated instances while API requests reuse the same
    backend object inside the process.
    """
    global _job_backend
    if _job_backend is None or _job_backend.job_store_path != settings.job_store_path:
        _job_backend = LocalJobBackend(settings.job_store_path)
    return _job_backend


def get_worker_registry() -> LocalWorkerRegistry:
    global _worker_registry
    if (
        _worker_registry is None
        or _worker_registry.worker_store_path != settings.worker_store_path
    ):
        _worker_registry = LocalWorkerRegistry(settings.worker_store_path)
    return _worker_registry


def _create_job_record(
    job_id: str,
    prompt: str,
    output_path: str,
    params: dict[str, Any],
    job_type: str = "generate",
    source_job_id: str | None = None,
    upscale_params: dict | None = None,
    payload: dict | None = None,
    source_output_path: str | None = None,
) -> dict[str, Any]:
    record = {
        "job_id": job_id,
        "status": "queued",
        "type": job_type,
        "prompt": prompt,
        "params": params,
        "output_path": output_path,
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "source_job_id": source_job_id,
        "upscale_params": upscale_params,
        "payload": payload or {},
        "source_output_path": source_output_path,
    }
    backend = get_job_backend()
    try:
        created = backend.create_job(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    broadcast_job_event("job_created", created)
    return created


def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    updated = get_job_backend().update_job(job_id, **updates)
    broadcast_job_event("job_updated", updated)
    return updated


def _get_job(job_id: str) -> dict[str, Any] | None:
    return get_job_backend().get_job(job_id)


def _job_id_from_version_id(version_id: str) -> str:
    if not version_id.startswith("ver_"):
        raise HTTPException(status_code=404, detail="Version not found")
    return version_id.removeprefix("ver_")


def _job_event_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {field: job.get(field) for field in _JOB_EVENT_FIELDS}


def _resolve_upscale_params(
    source_job: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    model_name = payload.get("model", "realesrgan-animevideov3")
    backend = UPSCALE_BACKENDS.get(model_name)
    if backend is None:
        known = ", ".join(sorted(UPSCALE_BACKENDS.keys())) or "none"
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model_name}. Known models: {known}",
        )

    if not get_worker_registry().has_upscale_model(
        model_name,
        stale_seconds=settings.worker_stale_seconds,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"No online worker currently advertises upscale model: {model_name}",
        )

    explicit_target_width = payload.get("target_width")
    explicit_target_height = payload.get("target_height")
    scale = payload.get("scale")

    src_params = source_job.get("params", {})
    src_w = src_params.get("width", 896)
    src_h = src_params.get("height", 448)

    if not scale and explicit_target_width is None and explicit_target_height is None:
        scale = backend.default_scale
    elif not scale:
        if explicit_target_width is not None:
            scale = explicit_target_width // src_w
        elif explicit_target_height is not None:
            scale = explicit_target_height // src_h
        if scale and scale < 1:
            scale = 1

    if not scale:
        scale = backend.default_scale

    validation_error = backend.validate_params(
        scale=scale,
        target_width=explicit_target_width,
        target_height=explicit_target_height,
    )
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    target_width = explicit_target_width
    target_height = explicit_target_height
    if backend.name == "seedvr2-3b" and target_width is None and target_height is None:
        target_width = src_w * scale
        target_height = src_h * scale

    return {
        "model": model_name,
        "scale": scale,
        "target_width": target_width,
        "target_height": target_height,
    }


def _collect_job_store_events(
    previous_snapshots: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    _reconcile_overdue_cancellations_for_read()
    current_snapshots: dict[str, dict[str, Any]] = {}
    events: list[dict[str, str]] = []

    for job in get_job_backend().list_jobs():
        job_id = str(job["job_id"])
        snapshot = _job_event_snapshot(job)
        current_snapshots[job_id] = snapshot

        if job_id not in previous_snapshots:
            events.append(_sse_event("job_created", job))
            continue

        if previous_snapshots[job_id] != snapshot:
            events.append(_sse_event("job_updated", job))

    for job_id in previous_snapshots:
        if job_id not in current_snapshots:
            events.append(_sse_event("job_deleted", {"job_id": job_id}))

    return current_snapshots, events


def _collect_result_store_events(known_versions: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    # Result workbench consumers reason about result/version state directly, so the SSE projection
    # must emit version events instead of leaking job-only updates into the new /api/events stream.
    results = build_result_summaries(get_job_backend().list_jobs())
    next_versions: dict[str, str] = {}
    events: list[dict[str, str]] = []
    for result in results:
        for version in result["versions"]:
            version_id = str(version["version_id"])
            status = str(version["status"])
            next_versions[version_id] = status
            if known_versions.get(version_id) != status:
                events.append(
                    _sse_event(
                        "version_updated" if version_id in known_versions else "version_created",
                        {
                            "result_id": result["result_id"],
                            "version_id": version_id,
                            "job_id": version["job_id"],
                            "status": status,
                            "download_url": version.get("download_url"),
                        },
                    )
                )
    return next_versions, events


@app.get("/")
def root() -> FileResponse:
    index_path = os.path.join(settings.frontend_dist_dir, "index.html")
    # The API must fail loudly when the React bundle is absent so deploy/test
    # mistakes do not silently fall back to a stale legacy shell.
    if not os.path.exists(index_path):
        raise HTTPException(
            status_code=503,
            detail="Frontend build not found. Run npm --prefix frontend run build.",
        )
    return FileResponse(index_path, media_type="text/html")


@app.get("/health")
def healthcheck() -> dict:
    panowan_engine_dir_exists = os.path.exists(settings.panowan_engine_dir)
    wan_model_ready = os.path.exists(
        settings.wan_diffusion_absolute_path
    ) and os.path.exists(settings.wan_t5_absolute_path)
    lora_exists = os.path.exists(settings.lora_absolute_path)
    model_ready = wan_model_ready and lora_exists
    # In the split topology the API container is intentionally CPU-only and does
    # not mount worker-only engine/model trees, so API readiness cannot depend on
    # local asset visibility without keeping /health stuck on "starting" forever.
    status = (
        "ready"
        if settings.service_title and os.getenv("SERVICE_ROLE", "api") == "api"
        else ("ready" if model_ready else "starting")
    )
    return {
        "status": status,
        "service_started": True,
        "model_ready": model_ready,
        "panowan_engine_dir_exists": panowan_engine_dir_exists,
        "wan_model_exists": wan_model_ready,
        "lora_exists": lora_exists,
    }


@app.post("/generate", status_code=202)
def generate(payload: dict) -> dict:
    if "negative_prompt" not in payload:
        payload["negative_prompt"] = ""
    task = payload.get("task") or payload.get("mode") or "t2v"
    if task not in {"t2v", "i2v"}:
        raise HTTPException(status_code=422, detail="task must be 't2v' or 'i2v'")
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    job_payload = dict(payload)
    job_payload["id"] = job_id
    job_payload["task"] = task
    params = resolve_inference_params(job_payload)
    record = _create_job_record(
        job_id, prompt, output_path, params, payload=job_payload
    )
    return {
        "job_id": job_id,
        "status": record["status"],
        "prompt": prompt,
        "output_path": output_path,
        "download_url": record["download_url"],
    }


def _create_result_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    job_payload = dict(payload)
    quality = str(job_payload.pop("quality", "custom"))
    params_payload = job_payload.pop("params", {}) or {}
    job_payload.update(params_payload)
    if "negative_prompt" not in job_payload:
        job_payload["negative_prompt"] = ""
    if quality == "draft":
        job_payload.setdefault("num_inference_steps", 20)
        job_payload.setdefault("width", 448)
        job_payload.setdefault("height", 224)
    elif quality == "standard":
        job_payload.setdefault("num_inference_steps", 50)
        job_payload.setdefault("width", 896)
        job_payload.setdefault("height", 448)
    generated = generate(job_payload)
    result_id = result_id_for_root_job(generated["job_id"])
    result = build_result_summary(result_id, get_job_backend().list_jobs())
    if result is None:
        raise HTTPException(
            status_code=500,
            detail="Created result could not be loaded",
        )
    expected_selected_version_id = version_id_for_job(generated["job_id"])
    # A freshly created result should project the queued root job as the selected
    # version so the workbench never receives a result shell without its only
    # version wired up.
    if result.get("selected_version_id") != expected_selected_version_id:
        raise HTTPException(
            status_code=500,
            detail="Created result did not include its root version",
        )
    return result


@app.get("/api/results")
def list_results_api() -> dict[str, Any]:
    return {"results": build_result_summaries(get_job_backend().list_jobs())}


@app.get("/api/results/{result_id}")
def get_result_api(result_id: str) -> dict[str, Any]:
    result = build_result_summary(result_id, get_job_backend().list_jobs())
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return {"result": result}


@app.post("/api/results", status_code=202)
def create_result_api(payload: dict) -> dict[str, Any]:
    return {"result": _create_result_from_payload(payload)}


@app.post("/upscale", status_code=202)
def upscale(payload: dict) -> dict:
    source_job_id = payload.get("source_job_id")
    if not source_job_id:
        raise HTTPException(status_code=400, detail="source_job_id is required")

    source_job = _get_job(source_job_id)
    if source_job is None:
        raise HTTPException(status_code=400, detail="Source job not found")
    if source_job["status"] != "succeeded":
        raise HTTPException(status_code=400, detail="Can only upscale completed jobs")
    if not os.path.exists(source_job["output_path"]):
        raise HTTPException(status_code=400, detail="Source video file not found")

    upscale_params = _resolve_upscale_params(source_job, payload)

    job_id = str(uuid.uuid4())
    output_path = os.path.join(settings.upscale_output_dir, f"output_{job_id}.mp4")
    source_output_path = source_job["output_path"]
    job_payload = {
        "source_job_id": source_job_id,
        "source_output_path": source_output_path,
        "output_path": output_path,
        "upscale_params": upscale_params,
    }

    record = _create_job_record(
        job_id,
        prompt=source_job.get("prompt", ""),
        output_path=output_path,
        params=source_job.get("params", {}),
        job_type="upscale",
        source_job_id=source_job_id,
        upscale_params=upscale_params,
        payload=job_payload,
        source_output_path=source_output_path,
    )

    return {
        "job_id": job_id,
        "status": record["status"],
        "type": "upscale",
        "source_job_id": source_job_id,
        "upscale_params": upscale_params,
    }


@app.post("/api/results/{result_id}/versions/{version_id}/upscale", status_code=202)
def create_upscale_version_api(result_id: str, version_id: str, payload: dict) -> dict[str, Any]:
    source_job_id = _job_id_from_version_id(version_id)
    result = build_result_summary(result_id, get_job_backend().list_jobs())
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    if not any(version["job_id"] == source_job_id for version in result["versions"]):
        raise HTTPException(status_code=404, detail="Version not found")

    # The result/version API contract uses workbench-facing model ids like
    # "seedvr2", but the worker runtime still dispatches by backend ids such as
    # "seedvr2-3b". Normalize only at the API boundary so persisted versions keep
    # the spec field name while queued jobs remain executable by the current worker.
    requested_model = payload.get("model")
    runtime_model = "seedvr2-3b" if requested_model == "seedvr2" else requested_model
    upscale_payload = {
        "source_job_id": source_job_id,
        "model": runtime_model,
        "scale_mode": payload.get("scale_mode", "factor"),
        "scale": payload.get("scale"),
        "target_width": payload.get("target_width"),
        "target_height": payload.get("target_height"),
        "replace_source": bool(payload.get("replace_source", False)),
    }
    created = upscale(upscale_payload)
    created_job_id = created["job_id"]
    if requested_model == "seedvr2":
        # Result projections and the React workbench spec speak in the simplified
        # "seedvr2" identifier, so rewrite only the persisted API-facing metadata
        # after queueing succeeds instead of asking the frontend to know worker ids.
        _update_job(created_job_id, upscale_params={**(created["upscale_params"] or {}), "model": "seedvr2"})
    version = None
    refreshed = build_result_summary(result_id, get_job_backend().list_jobs())
    if refreshed is not None:
        version = next((item for item in refreshed["versions"] if item["job_id"] == created_job_id), None)
    if version is None:
        raise HTTPException(status_code=500, detail="Created version could not be loaded")
    return {"version": version}


def _reconcile_overdue_cancellations_for_read() -> list[dict[str, Any]]:
    # Page refresh is a read path, but it is also the only chance to heal stale
    # cancelling records when no worker loop is alive to own the timeout.
    return reconcile_overdue_cancellations(get_job_backend(), now=datetime.now(UTC))


@app.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    _reconcile_overdue_cancellations_for_read()
    jobs = get_job_backend().list_jobs()
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs


@app.get("/jobs/events")
async def job_events(request: Request) -> Any:
    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        queue = subscribe()
        known_jobs = {
            job["job_id"]: _job_event_snapshot(job)
            for job in get_job_backend().list_jobs()
        }
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1)
                    event_name = event.get("event")
                    try:
                        payload = json.loads(event.get("data", "{}"))
                    except json.JSONDecodeError:
                        payload = None

                    if isinstance(payload, dict) and payload.get("job_id"):
                        job_id = str(payload["job_id"])
                        if event_name == "job_deleted":
                            known_jobs.pop(job_id, None)
                        elif event_name in {"job_created", "job_updated"}:
                            known_jobs[job_id] = _job_event_snapshot(payload)

                    yield event
                except TimeoutError:
                    known_jobs, store_events = _collect_job_store_events(known_jobs)
                    if store_events:
                        for event in store_events:
                            yield event
                        continue

                    if loop.time() - last_heartbeat >= 30:
                        last_heartbeat = loop.time()
                        yield {
                            "event": "heartbeat",
                            "data": json.dumps({"ts": now_iso()}),
                        }
        finally:
            unsubscribe(queue)

    return EventSourceResponse(event_generator())


@app.get("/api/events")
async def result_events(request: Request) -> Any:
    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        known_versions = {
            version["version_id"]: str(version["status"])
            for result in build_result_summaries(get_job_backend().list_jobs())
            for version in result["versions"]
        }
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()
        try:
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(1)
                known_versions, events = _collect_result_store_events(known_versions)
                for event in events:
                    yield event
                if not events and loop.time() - last_heartbeat >= 30:
                    last_heartbeat = loop.time()
                    yield _sse_event("heartbeat", {"ts": now_iso()})
        finally:
            return

    return EventSourceResponse(event_generator())


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "succeeded":
        raise HTTPException(status_code=409, detail=f"Job is {job['status']}")

    output_path = job["output_path"]
    if not os.path.exists(output_path):
        # Output disappeared after success: mark a non-canonical "missing
        # artifact" failure by re-routing through the lifecycle helpers if the
        # job is still owned by a worker. When the job is already terminal
        # (the common case here, since we only got past the status check via
        # "succeeded"), the safest action is to surface the 500 without
        # rewriting the terminal state — ADR 0010 forbids overwriting a
        # terminal record from outside the worker that produced it.
        raise HTTPException(status_code=500, detail="Output file not created")

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"{job_id}.mp4",
        headers={"X-Job-Id": job_id},
    )


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job["status"]
    if status == "queued":
        if get_job_backend().cancel_queued_job(job_id):
            cancelled = _get_job(job_id)
            if cancelled is None:
                raise HTTPException(status_code=404, detail="Job not found")
            broadcast_job_event("job_updated", cancelled)
            return cancelled
        job = _get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        status = job["status"]

    if status == "claimed":
        result = get_job_backend().request_cancellation(
            job_id, worker_id=job.get("worker_id")
        )
        if result is None:
            current = _get_job(job_id)
            if current is None:
                raise HTTPException(status_code=404, detail="Job not found")
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel job with status {current['status']}",
            )
        broadcast_job_event("job_updated", result)
        return result

    if status == "running":
        result = get_job_backend().request_cancellation(
            job_id, worker_id=job.get("worker_id")
        )
        if result is None:
            current = _get_job(job_id)
            if current is None:
                raise HTTPException(status_code=404, detail="Job not found")
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel job with status {current['status']}",
            )
        broadcast_job_event("job_updated", result)
        return result

    if status == "cancelling":
        return job

    if status == "failed" and job.get("error_code") == "cancel_timeout":
        worker_id = job.get("worker_id")
        if not worker_id:
            raise HTTPException(
                status_code=409,
                detail="Cannot retry cancellation without worker ownership",
            )
        result = get_job_backend().retry_timed_out_cancellation(
            job_id, worker_id=worker_id
        )
        if result is None:
            raise HTTPException(status_code=409, detail="Cannot retry cancellation")
        broadcast_job_event("job_updated", result)
        return result

    raise HTTPException(
        status_code=409, detail=f"Cannot cancel job with status {status}"
    )


@app.post("/jobs/{job_id}/cancel/escalate")
def escalate_cancel_job_endpoint(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    worker_id = job.get("worker_id")
    if not worker_id:
        raise HTTPException(status_code=409, detail="Job is not in cancelling state")
    result = get_job_backend().escalate_cancellation(job_id, worker_id=worker_id)
    if result is None:
        raise HTTPException(status_code=409, detail="Job is not in cancelling state")
    broadcast_job_event("job_updated", result)
    return result


@app.delete("/jobs/failed")
def delete_failed_jobs_endpoint() -> dict:
    """Delete failed and cancelled jobs from the store and notify SSE subscribers."""
    deleted = get_job_backend().delete_failed_jobs()
    for job_id in deleted:
        broadcast_job_event("job_deleted", {"job_id": job_id})
    return {"deleted": deleted, "count": len(deleted)}


def _worker_summary() -> dict[str, Any]:
    jobs = get_job_backend().list_jobs()
    registry = get_worker_registry()
    known_workers = registry.list_workers(stale_seconds=None)
    online_workers = registry.list_workers(stale_seconds=settings.worker_stale_seconds)
    online_ids = {str(worker.get("worker_id")) for worker in online_workers}
    cancelling_by_worker = {
        str(job.get("worker_id"))
        for job in jobs
        if job.get("status") == "cancelling" and job.get("worker_id")
    }
    busy_ids = {
        str(worker.get("worker_id"))
        for worker in online_workers
        if int(worker.get("running_jobs") or 0) > 0
    }
    total_capacity = sum(
        int(worker.get("max_concurrent_jobs") or 0)
        for worker in online_workers
    )
    occupied_capacity = sum(
        int(worker.get("running_jobs") or 0) for worker in online_workers
    )
    return {
        "known_workers": len(known_workers),
        "online_workers": len(online_workers),
        "busy_workers": len(busy_ids),
        "stuck_cancelling_workers": len(cancelling_by_worker & online_ids),
        "queued_jobs": sum(
            1 for job in jobs if job.get("status") in {"queued", "claimed"}
        ),
        "running_jobs": sum(1 for job in jobs if job.get("status") == "running"),
        "cancelling_jobs": sum(
            1 for job in jobs if job.get("status") == "cancelling"
        ),
        "total_capacity": total_capacity,
        "occupied_capacity": occupied_capacity,
        "effective_available_capacity": max(total_capacity - occupied_capacity, 0),
    }


@app.get("/api/runtime/summary")
def runtime_summary_api() -> dict[str, Any]:
    summary = _worker_summary()
    online_workers = int(summary.get("online_workers") or 0)
    busy_workers = int(summary.get("busy_workers") or 0)
    queued_jobs = int(summary.get("queued_jobs") or 0)
    running_jobs = int(summary.get("running_jobs") or 0)
    cancelling_jobs = int(summary.get("cancelling_jobs") or 0)
    total_capacity = int(summary.get("total_capacity") or 0)
    available_capacity = int(summary.get("effective_available_capacity") or 0)
    return {
        "capacity": total_capacity,
        "available_capacity": available_capacity,
        "online_workers": online_workers,
        "loading_workers": max(queued_jobs - available_capacity, 0),
        "busy_workers": busy_workers,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "cancelling_jobs": cancelling_jobs,
        "runtime_warm": online_workers > 0,
    }


@app.get("/workers/summary")
def worker_summary() -> dict[str, Any]:
    return _worker_summary()
