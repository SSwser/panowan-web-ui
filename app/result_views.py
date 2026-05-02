from __future__ import annotations

from collections import defaultdict
from typing import Any

TERMINAL_SUCCESS = {"succeeded", "completed"}
ACTIVE_STATUSES = {"queued", "claimed", "running", "cancelling"}
FAILED_STATUSES = {"failed"}
CANCELLED_STATUSES = {"cancelled"}


def build_result_summaries(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs_by_id = {str(job.get("job_id")): job for job in jobs if job.get("job_id")}
    root_by_job: dict[str, str] = {}

    for job_id, job in jobs_by_id.items():
        root_by_job[job_id] = _root_job_id(job, jobs_by_id)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job_id, job in jobs_by_id.items():
        grouped[root_by_job[job_id]].append(job)

    summaries = [_build_result_summary(root_job_id, group, jobs_by_id) for root_job_id, group in grouped.items()]
    summaries.sort(key=lambda result: str(result.get("updated_at") or result.get("created_at") or ""), reverse=True)
    return summaries


def build_result_summary(result_id: str, jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    summaries = build_result_summaries(jobs)
    for summary in summaries:
        if summary["result_id"] == result_id:
            return summary
    return None


def version_id_for_job(job_id: str) -> str:
    return f"ver_{job_id}"


def result_id_for_root_job(job_id: str) -> str:
    return f"res_{job_id}"


def _root_job_id(job: dict[str, Any], jobs_by_id: dict[str, dict[str, Any]]) -> str:
    current = job
    seen: set[str] = set()
    while current.get("source_job_id"):
        source_id = str(current["source_job_id"])
        if source_id in seen or source_id not in jobs_by_id:
            return source_id
        seen.add(source_id)
        current = jobs_by_id[source_id]
    return str(current.get("job_id"))


def _build_result_summary(root_job_id: str, jobs: list[dict[str, Any]], jobs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root_job = jobs_by_id.get(root_job_id) or min(jobs, key=_created_at)
    # Result timelines need stable parent-before-child ordering even when persisted
    # timestamps were backfilled or rewritten after the original generation finished.
    versions = [_build_version(job, jobs_by_id) for job in sorted(jobs, key=lambda job: _version_sort_key(job, jobs_by_id))]
    status = _aggregate_status([str(version["status"]) for version in versions])
    updated_at = max(str(job.get("finished_at") or job.get("updated_at") or job.get("created_at") or "") for job in jobs)
    selected_version = _selected_version(versions)
    return {
        "result_id": result_id_for_root_job(root_job_id),
        "root_job_id": root_job_id,
        "prompt": root_job.get("prompt", ""),
        "negative_prompt": root_job.get("payload", {}).get("negative_prompt", ""),
        "status": status,
        "selected_version_id": selected_version.get("version_id") if selected_version else None,
        "created_at": root_job.get("created_at"),
        "updated_at": updated_at,
        "versions": versions,
    }


def _build_version(job: dict[str, Any], jobs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    job_id = str(job["job_id"])
    source_job_id = job.get("source_job_id")
    upscale_params = job.get("upscale_params") or {}
    params = job.get("params") or {}
    is_upscale = job.get("type") == "upscale" or bool(source_job_id)
    width = upscale_params.get("width") or params.get("width")
    height = upscale_params.get("height") or params.get("height")
    return {
        "version_id": version_id_for_job(job_id),
        "job_id": job_id,
        "parent_version_id": version_id_for_job(str(source_job_id)) if source_job_id else None,
        "type": "upscale" if is_upscale else "original",
        "label": _version_label(job, upscale_params),
        "status": job.get("status", "queued"),
        "model": upscale_params.get("model"),
        "scale": upscale_params.get("scale"),
        "width": width,
        "height": height,
        "duration_seconds": job.get("duration_seconds"),
        "fps": job.get("fps"),
        "bitrate_mbps": job.get("bitrate_mbps"),
        "file_size_bytes": job.get("file_size_bytes"),
        "thumbnail_url": job.get("thumbnail_url"),
        "preview_url": job.get("download_url"),
        "download_url": job.get("download_url"),
        "params": params,
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
    }


def _version_label(job: dict[str, Any], upscale_params: dict[str, Any]) -> str:
    if job.get("type") != "upscale" and not job.get("source_job_id"):
        return "原始生成"
    scale = upscale_params.get("scale")
    model = str(upscale_params.get("model") or "Upscale")
    # Result cards surface model names directly to users, so preserve known brand casing
    # instead of blindly title-casing backend identifiers like seedvr2.
    display_model = _display_model_name(model)
    return f"{scale}x {display_model}" if scale else display_model


def _display_model_name(model: str) -> str:
    known_names = {
        "seedvr2": "SeedVR2",
    }
    normalized = model.strip().lower()
    if normalized in known_names:
        return known_names[normalized]
    return " ".join(part.capitalize() for part in model.replace("-", " ").split())


def _aggregate_status(statuses: list[str]) -> str:
    unique = set(statuses)
    if len(unique) == 1:
        return _result_status(statuses[0])
    if unique & ACTIVE_STATUSES and unique & (TERMINAL_SUCCESS | FAILED_STATUSES | CANCELLED_STATUSES):
        return "mixed"
    if unique <= TERMINAL_SUCCESS:
        return "completed"
    if unique <= FAILED_STATUSES:
        return "failed"
    if unique <= CANCELLED_STATUSES:
        return "cancelled"
    if unique & ACTIVE_STATUSES:
        return "running"
    return "mixed"


def _result_status(status: str) -> str:
    if status in TERMINAL_SUCCESS:
        return "completed"
    if status in FAILED_STATUSES:
        return "failed"
    if status in CANCELLED_STATUSES:
        return "cancelled"
    if status in ACTIVE_STATUSES:
        return "running" if status in {"claimed", "running", "cancelling"} else "queued"
    return status


def _selected_version(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    completed = [version for version in versions if version.get("status") in TERMINAL_SUCCESS]
    if completed:
        return completed[-1]
    return versions[-1] if versions else None


def _version_sort_key(job: dict[str, Any], jobs_by_id: dict[str, dict[str, Any]]) -> tuple[int, str, str]:
    depth = 0
    current = job
    seen: set[str] = set()
    while current.get("source_job_id"):
        source_id = str(current["source_job_id"])
        if source_id in seen or source_id not in jobs_by_id:
            break
        seen.add(source_id)
        depth += 1
        current = jobs_by_id[source_id]
    return (depth, _created_at(job), str(job.get("job_id") or ""))


def _created_at(job: dict[str, Any]) -> str:
    return str(job.get("created_at") or "")
