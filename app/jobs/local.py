"""Local file-backed job store.

Concurrency model:
- Uses an in-process ``threading.Lock``; safe under multiple threads in the
  *same* process.
- NOT safe for concurrent writers across multiple processes (e.g., simultaneous
  API + worker writes can lose updates). The current product runtime relies on
  ``max_concurrent_jobs=1`` and a single API + single worker; cross-process
  file locking is a known follow-up.
- Atomic file replace via ``os.replace(tmp, ...)`` prevents partial-file reads
  but does not prevent lost updates between processes.
"""

import copy
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalJobBackend:
    _ALLOWED_UPDATE_KEYS = frozenset({
        "status",
        "started_at",
        "finished_at",
        "error",
        "output_path",
        "worker_id",
        "download_url",
        "prompt",
        "params",
        "upscale_params",
        "source_job_id",
        "type",
    })

    def __init__(self, job_store_path: str):
        self.job_store_path = job_store_path
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self.restore()

    def restore(self) -> None:
        if not os.path.exists(self.job_store_path):
            return
        with open(self.job_store_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_jobs = payload.get("jobs", payload)
        if not isinstance(raw_jobs, dict):
            raise ValueError("Job store payload must contain a jobs object")
        with self._lock:
            self._jobs = {
                str(job_id): self._normalize_job_record(str(job_id), record)
                for job_id, record in raw_jobs.items()
                if isinstance(record, dict)
            }
            self._persist_unlocked()

    def create_job(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["job_id"])
        normalized = self._normalize_job_record(job_id, record, restore=False)
        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"Job {job_id} already exists")
            self._jobs[job_id] = normalized
            self._persist_unlocked()
            return copy.deepcopy(normalized)

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        unknown = set(updates) - self._ALLOWED_UPDATE_KEYS
        if unknown:
            raise ValueError(f"Unknown job fields: {sorted(unknown)}")
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            self._jobs[job_id].update(updates)
            self._persist_unlocked()
            return copy.deepcopy(self._jobs[job_id])

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [copy.deepcopy(job) for job in self._jobs.values()]
        jobs.sort(key=lambda job: job.get("created_at") or "", reverse=True)
        return jobs

    def claim_next_job(self, worker_id: str) -> dict[str, Any] | None:
        with self._lock:
            queued = sorted(
                (job for job in self._jobs.values() if job.get("status") == "queued"),
                key=lambda job: job.get("created_at") or "",
            )
            if not queued:
                return None
            job = queued[0]
            job["status"] = "running"
            job["started_at"] = now_iso()
            job["worker_id"] = worker_id
            self._persist_unlocked()
            return copy.deepcopy(job)

    def fail_job(self, job_id: str, error: str) -> dict[str, Any]:
        return self.update_job(job_id, status="failed", finished_at=now_iso(), error=error)

    def complete_job(self, job_id: str, output_path: str) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="completed",
            finished_at=now_iso(),
            output_path=output_path,
        )

    def _normalize_job_record(
        self, job_id: str, record: dict[str, Any], restore: bool = True
    ) -> dict[str, Any]:
        normalized = copy.deepcopy(record)
        normalized["job_id"] = str(normalized.get("job_id") or job_id)
        normalized.setdefault("download_url", f"/jobs/{normalized['job_id']}/download")
        normalized.setdefault("prompt", "")
        normalized.setdefault("params", {})
        normalized.setdefault("output_path", "")
        normalized.setdefault("created_at", now_iso())
        normalized.setdefault("started_at", None)
        normalized.setdefault("finished_at", None)
        normalized.setdefault("error", None)
        normalized.setdefault("status", "queued")
        normalized.setdefault("type", "generate")
        normalized.setdefault("source_job_id", None)
        normalized.setdefault("upscale_params", None)
        normalized.setdefault("worker_id", None)
        if restore and normalized["status"] in {"queued", "running"}:
            normalized["status"] = "failed"
            normalized["finished_at"] = normalized["finished_at"] or now_iso()
            normalized["error"] = "Service restarted before the job completed"
        return normalized

    def _persist_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self.job_store_path), exist_ok=True)
        temp_path = f"{self.job_store_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"jobs": self._jobs}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, self.job_store_path)
