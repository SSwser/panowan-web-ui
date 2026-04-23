import json
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse

from .generator import (
    extract_prompt,
    generate_video,
    log_startup_diagnostics,
    resolve_inference_params,
)
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
    return record


def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    with _jobs_lock:
        if job_id not in _jobs:
            raise KeyError(job_id)
        _jobs[job_id].update(updates)
        _persist_jobs_unlocked()
        return dict(_jobs[job_id])


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


@app.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs


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
