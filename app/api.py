import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .sse import broadcast_job_event, subscribe, unsubscribe

from .generator import extract_prompt, resolve_inference_params
from .upscaler import UPSCALE_BACKENDS
from .jobs import LocalJobBackend, LocalWorkerRegistry, now_iso
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        get_job_backend().restore()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not restore jobs from disk: {exc}", flush=True)
    yield


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

    target_width = payload.get("target_width")
    target_height = payload.get("target_height")
    scale = payload.get("scale")

    src_params = source_job.get("params", {})
    src_w = src_params.get("width", 896)
    src_h = src_params.get("height", 448)

    if not scale and not target_width and not target_height:
        scale = backend.default_scale
    elif not scale:
        if target_width:
            scale = target_width // src_w
        elif target_height:
            scale = target_height // src_h
        if scale and scale < 1:
            scale = 1

    if not scale:
        scale = backend.default_scale

    if target_width is None and target_height is None:
        target_width = src_w * scale
        target_height = src_h * scale

    validation_error = backend.validate_params(
        scale=scale,
        target_width=target_width,
        target_height=target_height,
    )
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    return {
        "model": model_name,
        "scale": scale,
        "target_width": target_width,
        "target_height": target_height,
    }


def _collect_job_store_events(
    previous_snapshots: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
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


@app.get("/")
def root() -> FileResponse:
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    return FileResponse(index_path, media_type="text/html")


@app.get("/health")
def healthcheck() -> dict:
    panowan_engine_dir_exists = os.path.exists(settings.panowan_engine_dir)
    wan_model_ready = os.path.exists(
        settings.wan_diffusion_absolute_path
    ) and os.path.exists(settings.wan_t5_absolute_path)
    lora_exists = os.path.exists(settings.lora_absolute_path)
    model_ready = wan_model_ready and lora_exists

    return {
        "status": "ready" if model_ready else "starting",
        "service_started": True,
        "model_ready": model_ready,
        "panowan_engine_dir_exists": panowan_engine_dir_exists,
        "wan_model_exists": wan_model_ready,
        "lora_exists": lora_exists,
    }


@app.post("/generate", status_code=202)
def generate(payload: dict) -> dict:
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    job_payload = dict(payload)
    job_payload["id"] = job_id
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


@app.post("/upscale", status_code=202)
def upscale(payload: dict) -> dict:
    source_job_id = payload.get("source_job_id")
    if not source_job_id:
        raise HTTPException(status_code=400, detail="source_job_id is required")

    source_job = _get_job(source_job_id)
    if source_job is None:
        raise HTTPException(status_code=400, detail="Source job not found")
    if source_job["status"] != "completed":
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


@app.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
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
                except asyncio.TimeoutError:
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

    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Job is {job['status']}")

    output_path = job["output_path"]
    if not os.path.exists(output_path):
        _update_job(
            job_id,
            status="failed",
            finished_at=now_iso(),
            error="Output file missing",
        )
        raise HTTPException(status_code=500, detail="Output file not created")

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"{job_id}.mp4",
        headers={"X-Job-Id": job_id},
    )


def cancel_job(job_id: str, force: bool = False) -> dict:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job["status"]
    if status == "queued":
        return _update_job(
            job_id,
            status="failed",
            error="Cancelled by user",
            finished_at=now_iso(),
        )

    if status == "running":
        if not force:
            return {
                "warning": True,
                "job_id": job_id,
                "status": "running",
                "message": (
                    "Job is currently running. Force termination may cause "
                    "incomplete output. Set force=true to confirm."
                ),
                "pid": None,
            }
        # Force-cancel is worker-driven: flip the persisted job status and let
        # the polling worker observe `_should_cancel()` and terminate its own
        # subprocess tree on the next cancellation check.
        return _update_job(
            job_id,
            status="failed",
            error="Cancelled by user",
            finished_at=now_iso(),
        )

    # completed or failed
    raise HTTPException(
        status_code=409, detail=f"Cannot cancel job with status {status}"
    )


@app.post("/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, payload: dict = None) -> dict:
    payload = payload or {}
    force = payload.get("force", False)
    result = cancel_job(job_id, force=force)
    if result.get("warning"):
        return JSONResponse(content=result, status_code=202)
    return result


@app.delete("/jobs/failed")
def delete_failed_jobs_endpoint() -> dict:
    """Delete all failed jobs from the store and notify SSE subscribers."""
    deleted = get_job_backend().delete_failed_jobs()
    for job_id in deleted:
        broadcast_job_event("job_deleted", {"job_id": job_id})
    return {"deleted": deleted, "count": len(deleted)}
