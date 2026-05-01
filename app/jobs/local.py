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
import threading
import time
from datetime import UTC, datetime
from typing import Any

from app.jobs.lifecycle import (
    INFLIGHT_STATES,
    JOB_STATE_CANCELLED,
    JOB_STATE_CANCELLING,
    JOB_STATE_CLAIMED,
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    JOB_STATE_SUCCEEDED,
    can_transition,
    normalize_legacy_record,
    normalize_restored_inflight_record,
)

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _env_flag(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        dev_mode = _env_flag("DEV_MODE")
        with self._locked_store():
            self._jobs = {
                str(job_id): self._normalize_job_record(
                    str(job_id), record, restore=not dev_mode
                )
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
        """Move the oldest queued job to ``claimed`` ownership.

        Per ADR 0010 the ``claimed`` state asserts ownership but does not
        announce execution start; that transition belongs to ``mark_running``.
        """
        with self._locked_store():
            queued = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.get("status") == JOB_STATE_QUEUED
                ),
                key=lambda job: job.get("created_at") or "",
            )
            if not queued:
                return None
            job = queued[0]
            job["status"] = JOB_STATE_CLAIMED
            job["worker_id"] = worker_id
            self._persist_unlocked()
            return copy.deepcopy(job)

    def mark_running(
        self, job_id: str, worker_id: str
    ) -> dict[str, Any] | None:
        """Move a claimed job owned by ``worker_id`` into ``running``.

        Returns ``None`` if the job is missing, owned by a different worker,
        or is no longer in a state that can legally start running. Refusing
        the write here is the first-pass stale-writer guard required by ADR
        0010 §7.
        """
        return self._guarded_transition(
            job_id,
            worker_id=worker_id,
            target_state=JOB_STATE_RUNNING,
            allowed_current_states={JOB_STATE_CLAIMED},
            extra_fields={"started_at": now_iso(), "error": None},
        )

    def mark_succeeded(
        self, job_id: str, worker_id: str, output_path: str
    ) -> dict[str, Any] | None:
        """Finalize a running job as ``succeeded`` for its current owner.

        Refuses to overwrite a terminal state (including ``cancelled``),
        which preserves the ADR 0010 rule that observed cancellation is not
        retroactively rewritten by a late success report.
        """
        return self._guarded_transition(
            job_id,
            worker_id=worker_id,
            target_state=JOB_STATE_SUCCEEDED,
            allowed_current_states={JOB_STATE_RUNNING},
            extra_fields={
                "finished_at": now_iso(),
                "output_path": output_path,
                "error": None,
            },
        )

    def mark_failed(
        self, job_id: str, worker_id: str, error: str
    ) -> dict[str, Any] | None:
        """Finalize an owned in-flight job as ``failed`` with an error string.

        Allowed from ``claimed``, ``running``, or ``cancelling`` because each
        of those is a legal precondition for a runtime failure terminating
        the attempt.
        """
        return self._guarded_transition(
            job_id,
            worker_id=worker_id,
            target_state=JOB_STATE_FAILED,
            allowed_current_states={
                JOB_STATE_CLAIMED,
                JOB_STATE_RUNNING,
                JOB_STATE_CANCELLING,
            },
            extra_fields={"finished_at": now_iso(), "error": error},
        )

    def request_cancellation(
        self, job_id: str, *, finished: bool = False
    ) -> dict[str, Any] | None:
        """Record cancellation intent or finalize cooperative cancellation.

        - From ``queued`` it transitions directly to terminal ``cancelled``.
        - From ``claimed`` or ``running`` it transitions to the intermediate
          ``cancelling`` state that signals user intent to the worker.
        - With ``finished=True`` from ``cancelling`` it transitions to the
          terminal ``cancelled`` state once cooperative cancellation has
          actually been honored.

        Returns the updated job record, or ``None`` if no legal transition
        applies (e.g., the job is already terminal or does not exist).
        """
        with self._locked_store():
            job = self._jobs.get(job_id)
            if job is None:
                return None
            current = job.get("status")
            if finished and current == JOB_STATE_CANCELLING:
                target = JOB_STATE_CANCELLED
                extras = {"finished_at": now_iso(), "error": None}
            elif current == JOB_STATE_QUEUED:
                target = JOB_STATE_CANCELLED
                extras = {"finished_at": now_iso(), "error": None}
            elif current in {JOB_STATE_CLAIMED, JOB_STATE_RUNNING}:
                target = JOB_STATE_CANCELLING
                extras = {}
            else:
                return None
            if not can_transition(current, target):
                return None
            job["status"] = target
            for key, value in extras.items():
                job[key] = value
            self._persist_unlocked()
            return copy.deepcopy(job)

    def cancel_queued_job(self, job_id: str) -> bool:
        """Backward-compatible queued-only cancellation entry point.

        Kept as a boolean for callers that already use it; new code should
        prefer ``request_cancellation`` so cancellation flows through one
        canonical path regardless of starting state.
        """
        result = self.request_cancellation(job_id)
        return bool(result is not None and result["status"] == JOB_STATE_CANCELLED)

    def _guarded_transition(
        self,
        job_id: str,
        *,
        worker_id: str,
        target_state: str,
        allowed_current_states: set[str],
        extra_fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Apply a worker-owned transition under canonical and ownership rules.

        Three guards must pass before any write happens: the job exists, the
        caller already owns it, and the canonical transition graph permits
        the move from the current state. This is the implementation seam
        ADR 0010 §7 calls out for stale-writer rejection in a store that does
        not yet persist explicit version numbers.
        """
        with self._locked_store():
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.get("worker_id") != worker_id:
                return None
            current = job.get("status")
            if current not in allowed_current_states:
                return None
            if not can_transition(current, target_state):
                return None
            job["status"] = target_state
            for key, value in extra_fields.items():
                job[key] = value
            self._persist_unlocked()
            return copy.deepcopy(job)

    def delete_failed_jobs(self) -> list[str]:
        """Remove all failed jobs from the store. Returns the deleted job IDs."""
        with self._locked_store():
            failed_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.get("status") == JOB_STATE_FAILED
            ]
            for job_id in failed_ids:
                self._delete_job_artifacts_unlocked(self._jobs[job_id])
                del self._jobs[job_id]
            if failed_ids:
                self._persist_unlocked()
        return failed_ids

    def _delete_job_artifacts_unlocked(self, job: dict[str, Any]) -> None:
        output_path = job.get("output_path")
        if not output_path or not os.path.isfile(output_path):
            return
        try:
            os.remove(output_path)
        except OSError:
            pass

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
        normalized.setdefault("status", JOB_STATE_QUEUED)
        normalized.setdefault("type", "generate")
        normalized.setdefault("source_job_id", None)
        normalized.setdefault("upscale_params", None)
        normalized.setdefault("worker_id", None)
        # Always map legacy persisted labels (`completed`, failed-as-cancellation)
        # into canonical states so downstream code never has to know the old
        # vocabulary.
        normalized = normalize_legacy_record(normalized)
        if restore:
            # Restore biases uncertain in-flight work toward explicit failure.
            # Fabricating success here would silently mask a missing artifact.
            normalized = normalize_restored_inflight_record(normalized, now_iso())
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
        with open(self.job_store_path, encoding="utf-8") as handle:
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
