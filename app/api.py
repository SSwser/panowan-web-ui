import asyncio
import json
import os
import subprocess
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .sse import broadcast_job_event, subscribe, unsubscribe

from .generator import (
    extract_prompt,
    generate_video,
    log_startup_diagnostics,
    resolve_inference_params,
)
from .upscaler import UPSCALE_BACKENDS, upscale_video
from .settings import settings


app = FastAPI(
    title=settings.service_title,
    description="Run PanoWan video generation inside a local Docker container.",
    version=settings.service_version,
)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_gpu_slot = threading.Semaphore(1)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_download_url(job_id: str) -> str:
    return f"/jobs/{job_id}/download"


def _persist_jobs_unlocked() -> None:
    os.makedirs(os.path.dirname(settings.job_store_path), exist_ok=True)
    temp_path = f"{settings.job_store_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump({"jobs": _jobs}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, settings.job_store_path)


def _normalize_job_record(job_id: str, record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["job_id"] = str(normalized.get("job_id") or job_id)
    normalized["download_url"] = _job_download_url(normalized["job_id"])
    normalized.setdefault("prompt", settings.default_prompt)
    normalized.setdefault("params", {})
    normalized.setdefault("output_path", "")
    normalized.setdefault("created_at", _now_iso())
    normalized.setdefault("started_at", None)
    normalized.setdefault("finished_at", None)
    normalized.setdefault("error", None)
    normalized.setdefault("status", "queued")
    normalized.setdefault("type", "generate")
    normalized.setdefault("source_job_id", None)
    normalized.setdefault("upscale_params", None)

    if normalized["status"] in {"queued", "running"}:
        normalized["status"] = "failed"
        normalized["finished_at"] = normalized["finished_at"] or _now_iso()
        normalized["error"] = "Service restarted before the job completed"
    elif normalized["status"] == "completed" and not os.path.exists(
        normalized["output_path"]
    ):
        normalized["status"] = "failed"
        normalized["finished_at"] = normalized["finished_at"] or _now_iso()
        normalized["error"] = "Output file missing after service restart"

    return normalized


def _restore_jobs_from_disk() -> None:
    if not os.path.exists(settings.job_store_path):
        return

    with open(settings.job_store_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_jobs = payload.get("jobs", payload)
    if not isinstance(raw_jobs, dict):
        raise ValueError("Job store payload must contain a jobs object")

    restored_jobs = {
        str(job_id): _normalize_job_record(str(job_id), record)
        for job_id, record in raw_jobs.items()
        if isinstance(record, dict)
    }

    with _jobs_lock:
        _jobs.clear()
        _jobs.update(restored_jobs)
        _persist_jobs_unlocked()


def _create_job_record(
    job_id: str, prompt: str, output_path: str, params: dict[str, Any],
    job_type: str = "generate",
    source_job_id: str | None = None,
    upscale_params: dict | None = None,
) -> dict[str, Any]:
    record = {
        "job_id": job_id,
        "status": "queued",
        "type": job_type,
        "prompt": prompt,
        "params": params,
        "output_path": output_path,
        "download_url": _job_download_url(job_id),
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "source_job_id": source_job_id,
        "upscale_params": upscale_params,
    }
    with _jobs_lock:
        if job_id in _jobs:
            raise ValueError(f"Job {job_id} already exists")
        _jobs[job_id] = record
        _persist_jobs_unlocked()
    broadcast_job_event("job_created", record)
    return record


def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    with _jobs_lock:
        if job_id not in _jobs:
            raise KeyError(job_id)
        _jobs[job_id].update(updates)
        _persist_jobs_unlocked()
        result = dict(_jobs[job_id])
    broadcast_job_event("job_updated", {**updates, "job_id": job_id})
    return result


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def _run_generation_job(job_id: str, payload: dict) -> None:
    try:
        _update_job(job_id, status="running", started_at=_now_iso())
        with _gpu_slot:
            result = generate_video(payload)
        _update_job(
            job_id,
            status="completed",
            finished_at=_now_iso(),
            output_path=result["output_path"],
        )
    except Exception as exc:
        print(f"ERROR: job {job_id} failed: {exc}", flush=True)
        traceback.print_exc()
        try:
            _update_job(
                job_id,
                status="failed",
                finished_at=_now_iso(),
                error=str(exc),
            )
        except KeyError:
            pass


def _run_upscale_job(
    job_id: str, input_path: str, output_path: str, upscale_params: dict
) -> None:
    try:
        _update_job(job_id, status="running", started_at=_now_iso())
        with _gpu_slot:
            result = upscale_video(
                input_path=input_path,
                output_path=output_path,
                model=upscale_params["model"],
                scale=upscale_params["scale"],
                target_width=upscale_params.get("target_width"),
                target_height=upscale_params.get("target_height"),
                model_dir=settings.upscale_model_dir,
                timeout_seconds=settings.upscale_timeout_seconds,
            )
        _update_job(
            job_id,
            status="completed",
            finished_at=_now_iso(),
            output_path=result["output_path"],
        )
    except Exception as exc:
        print(f"ERROR: upscale job {job_id} failed: {exc}", flush=True)
        traceback.print_exc()
        try:
            _update_job(
                job_id,
                status="failed",
                finished_at=_now_iso(),
                error=str(exc),
            )
        except KeyError:
            pass


@app.on_event("startup")
def on_startup() -> None:
    try:
        _restore_jobs_from_disk()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not restore jobs from disk: {exc}", flush=True)
    log_startup_diagnostics()


@app.get("/")
def root() -> FileResponse:
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    return FileResponse(index_path, media_type="text/html")


@app.get("/health")
def healthcheck() -> dict:
    panowan_dir_exists = os.path.exists(settings.panowan_dir)
    wan_model_ready = os.path.exists(
        settings.wan_diffusion_absolute_path
    ) and os.path.exists(settings.wan_t5_absolute_path)
    lora_exists = os.path.exists(settings.lora_absolute_path)
    model_ready = wan_model_ready and lora_exists

    return {
        "status": "ready" if model_ready else "starting",
        "service_started": True,
        "model_ready": model_ready,
        "panowan_dir_exists": panowan_dir_exists,
        "wan_model_exists": wan_model_ready,
        "lora_exists": lora_exists,
    }


@app.post("/generate", status_code=202)
def generate(payload: dict, background_tasks: BackgroundTasks) -> dict:
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    job_payload = dict(payload)
    job_payload["id"] = job_id
    params = resolve_inference_params(job_payload)

    try:
        _create_job_record(job_id, prompt, output_path, params)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    background_tasks.add_task(_run_generation_job, job_id, job_payload)

    return {
        "job_id": job_id,
        "status": "queued",
        "prompt": prompt,
        "output_path": output_path,
        "download_url": _job_download_url(job_id),
    }


@app.post("/upscale", status_code=202)
def upscale(payload: dict, background_tasks: BackgroundTasks) -> dict:
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

    model_name = payload.get("model", "realesrgan-animevideov3")
    backend = UPSCALE_BACKENDS.get(model_name)
    if backend is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")

    # Resolve scale
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

    # Validate
    validation_error = backend.validate_params(scale, src_w, src_h)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    # Calculate target dimensions if not provided
    if target_width is None and target_height is None:
        target_width = src_w * scale
        target_height = src_h * scale

    job_id = str(uuid.uuid4())
    output_path = os.path.join(settings.upscale_output_dir, f"output_{job_id}.mp4")
    upscale_params = {
        "model": model_name,
        "scale": scale,
        "target_width": target_width,
        "target_height": target_height,
    }

    try:
        _create_job_record(
            job_id,
            prompt=source_job.get("prompt", ""),
            output_path=output_path,
            params=source_job.get("params", {}),
            job_type="upscale",
            source_job_id=source_job_id,
            upscale_params=upscale_params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    background_tasks.add_task(
        _run_upscale_job, job_id, source_job["output_path"], output_path, upscale_params
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "type": "upscale",
        "source_job_id": source_job_id,
        "upscale_params": upscale_params,
    }


@app.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs


@app.get("/jobs/events")
async def job_events(request: Request) -> Any:
    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        queue = subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield event
                except asyncio.TimeoutError:
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"ts": _now_iso()}),
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
            finished_at=_now_iso(),
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
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        status = job["status"]
        if status == "queued":
            job["status"] = "failed"
            job["error"] = "Cancelled by user"
            job["finished_at"] = _now_iso()
            _persist_jobs_unlocked()
            result = dict(job)
            result.pop("_process", None)
            return result

        if status == "running":
            if not force:
                process = job.get("_process")
                return {
                    "warning": True,
                    "job_id": job_id,
                    "status": "running",
                    "message": "Job is currently running. Force termination may cause incomplete output. Set force=true to confirm.",
                    "pid": process.pid if process else None,
                }
            # Two-phase termination
            process = job.get("_process")
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        job.pop("_process", None)
                        job["status"] = "failed"
                        job["error"] = "Cancel failed: process unkillable"
                        job["finished_at"] = _now_iso()
                        _persist_jobs_unlocked()
                        raise HTTPException(status_code=500, detail="Cancel failed: process unkillable")
            job.pop("_process", None)
            job["status"] = "failed"
            job["error"] = "Cancelled by user"
            job["finished_at"] = _now_iso()
            _persist_jobs_unlocked()
            result = dict(job)
            result.pop("_process", None)
            return result

        # completed or failed
        raise HTTPException(status_code=409, detail=f"Cannot cancel job with status {status}")


@app.post("/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, payload: dict = None) -> dict:
    payload = payload or {}
    force = payload.get("force", False)
    result = cancel_job(job_id, force=force)
    if result.get("warning"):
        return JSONResponse(content=result, status_code=202)
    return result
