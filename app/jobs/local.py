"""Local file-backed job store.

Concurrency model:
- Uses an in-process ``threading.Lock`` plus a sidecar file lock to serialize
    writers across API and worker processes.
- Reloads the latest on-disk state inside each critical section so multiple
    backend instances do not overwrite each other's view of the queue.
- Atomic file replace via ``os.replace(tmp, ...)`` prevents partial-file reads.
"""

import copy
import json
import os
import time
import threading
from datetime import datetime, timezone
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalJobBackend:
    _ALLOWED_UPDATE_KEYS = frozenset(
        {
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
        }
    )

    def __init__(self, job_store_path: str):
        self.job_store_path = job_store_path
        self._lock = threading.Lock()
        self._lock_path = f"{job_store_path}.lock"
        self._jobs: dict[str, dict[str, Any]] = {}
        self._load_from_disk()

    def restore(self) -> None:
        with self._locked_store():
            self._jobs = {
                str(job_id): self._normalize_job_record(str(job_id), record)
                for job_id, record in self._jobs.items()
                if isinstance(record, dict)
            }
            self._persist_unlocked()

    def _load_from_disk(self) -> None:
        with self._locked_store():
            return

    def create_job(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["job_id"])
        normalized = self._normalize_job_record(job_id, record, restore=False)
        with self._locked_store():
            if job_id in self._jobs:
                raise ValueError(f"Job {job_id} already exists")
            self._jobs[job_id] = normalized
            self._persist_unlocked()
            return copy.deepcopy(normalized)

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        unknown = set(updates) - self._ALLOWED_UPDATE_KEYS
        if unknown:
            raise ValueError(f"Unknown job fields: {sorted(unknown)}")
        with self._locked_store():
            if job_id not in self._jobs:
                raise KeyError(job_id)
            self._jobs[job_id].update(updates)
            self._persist_unlocked()
            return copy.deepcopy(self._jobs[job_id])

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._locked_store():
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._locked_store():
            jobs = [copy.deepcopy(job) for job in self._jobs.values()]
        jobs.sort(key=lambda job: job.get("created_at") or "", reverse=True)
        return jobs

    def claim_next_job(self, worker_id: str) -> dict[str, Any] | None:
        with self._locked_store():
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
        return self.update_job(
            job_id, status="failed", finished_at=now_iso(), error=error
        )

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
        _ensure_parent_dir(self.job_store_path)
        temp_path = f"{self.job_store_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"jobs": self._jobs}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, self.job_store_path)

    def _load_jobs_unlocked(self) -> None:
        if not os.path.exists(self.job_store_path):
            self._jobs = {}
            return
        with open(self.job_store_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_jobs = payload.get("jobs", payload)
        if not isinstance(raw_jobs, dict):
            raise ValueError("Job store payload must contain a jobs object")
        self._jobs = {
            str(job_id): record
            for job_id, record in raw_jobs.items()
            if isinstance(record, dict)
        }

    def _locked_store(self) -> "_StoreLock":
        return _StoreLock(self)


class _StoreLock:
    def __init__(self, backend: LocalJobBackend):
        self._backend = backend
        self._handle = None

    def __enter__(self) -> "_StoreLock":
        self._backend._lock.acquire()
        _ensure_parent_dir(self._backend._lock_path)
        self._handle = open(self._backend._lock_path, "a+b")
        _prepare_lock_file(self._handle)
        _acquire_file_lock(self._handle)
        self._backend._load_jobs_unlocked()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._handle is not None:
                _release_file_lock(self._handle)
                self._handle.close()
        finally:
            self._backend._lock.release()


def _ensure_parent_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _prepare_lock_file(handle) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)


def _acquire_file_lock(handle) -> None:
    if os.name == "nt":
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.01)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(handle) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
