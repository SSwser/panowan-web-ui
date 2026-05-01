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
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.cancellation import (
    CancellationCapability,
    begin_cancellation,
    escalate_cancellation as _escalate_cancellation,
)
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


_DEFAULT_CANCEL_TIMEOUT_SEC = 45
_DEFAULT_CANCEL_POLL_INTERVAL_SEC = 1


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
            "error_code",
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
        self,
        job_id: str,
        *,
        worker_id: str | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        """Record cancellation intent or finalize cooperative cancellation.

        - From ``queued`` it transitions directly to terminal ``cancelled``.
        - From ``claimed`` or ``running`` it transitions to the intermediate
          ``cancelling`` state, attaching governance metadata
          (``cancel_mode``, ``cancel_attempt``, ``cancel_requested_at``,
          ``cancel_deadline_at``) sourced from the per-job
          :class:`CancellationCapability`.
        - With ``finished=True`` from ``cancelling`` it transitions to the
          terminal ``cancelled`` state once cooperative cancellation has
          actually been honored.

        When ``worker_id`` is provided and the current state is owned
        (``claimed``/``running``/``cancelling``), ownership is enforced and
        a mismatch returns ``None``. When omitted, the API caller path is
        preserved: any legal transition for the current state is applied.
        """
        if finished:
            result = self._guarded_transition(
                job_id,
                worker_id=worker_id,
                target_state=JOB_STATE_CANCELLED,
                allowed_current_states={JOB_STATE_CANCELLING},
                extra_fields={"finished_at": now_iso(), "error": None},
            )
            if result is not None:
                return result
        # Queued jobs are not owned by any worker, so skip the ownership
        # check on this branch even when the caller supplied a worker_id.
        result = self._guarded_transition(
            job_id,
            worker_id=None,
            target_state=JOB_STATE_CANCELLED,
            allowed_current_states={JOB_STATE_QUEUED},
            extra_fields={"finished_at": now_iso(), "error": None},
        )
        if result is not None:
            return result
        return self._guarded_transition(
            job_id,
            worker_id=worker_id,
            target_state=JOB_STATE_CANCELLING,
            allowed_current_states={JOB_STATE_CLAIMED, JOB_STATE_RUNNING},
            extra_fields_factory=lambda job: begin_cancellation(
                job,
                capability=self._cancellation_capability_for_job(job),
                now=datetime.now(UTC),
            ),
        )

    def escalate_cancellation(
        self, job_id: str, *, worker_id: str
    ) -> dict[str, Any] | None:
        """Bump a cancelling job to escalated mode and refresh its deadline.

        Allowed only from ``cancelling`` state by the owning worker.
        """
        return self._guarded_transition(
            job_id,
            worker_id=worker_id,
            target_state=JOB_STATE_CANCELLING,
            allowed_current_states={JOB_STATE_CANCELLING},
            extra_fields_factory=lambda job: _escalate_cancellation(
                job,
                capability=self._cancellation_capability_for_job(job),
                now=datetime.now(UTC),
            ),
        )

    def finalize_cancellation_timeout(
        self,
        job_id: str,
        *,
        worker_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        """Force a stuck cancelling job to terminal ``failed`` with ``error_code``.

        Used by worker reconciliation when the cancel deadline elapses without
        cooperative convergence. Only the owning worker may finalize.
        """
        return self._guarded_transition(
            job_id,
            worker_id=worker_id,
            target_state=JOB_STATE_FAILED,
            allowed_current_states={JOB_STATE_CANCELLING},
            extra_fields={
                "finished_at": now_iso(),
                "error": reason,
                "error_code": reason,
            },
        )

    def _cancellation_capability_for_job(
        self, _job: dict[str, Any]
    ) -> CancellationCapability:
        # Task 3 will look up per-engine capability from job["type"].
        return CancellationCapability(
            supports_soft_cancel=True,
            supports_escalated_cancel=True,
            default_cancel_timeout_sec=_DEFAULT_CANCEL_TIMEOUT_SEC,
            cancel_poll_interval_sec=_DEFAULT_CANCEL_POLL_INTERVAL_SEC,
            cancel_checkpoint_granularity="checkpoint",
        )

    def cancel_queued_job(self, job_id: str) -> bool:
        """Backward-compatible queued-only cancellation entry point.

        Returns True iff the job was in the queued state at observation time
        and was atomically transitioned to terminal ``cancelled``. Refuses to
        act on jobs already owned by a worker — those must flow through the
        cooperative ``request_cancellation`` path so the worker can observe
        the cancel intent before any terminal write happens.
        """
        with self._locked_store():
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.get("status") != JOB_STATE_QUEUED:
                return False
            job["status"] = JOB_STATE_CANCELLED
            job["finished_at"] = now_iso()
            job["error"] = None
            self._persist_unlocked()
            return True

    def _guarded_transition(
        self,
        job_id: str,
        *,
        target_state: str,
        allowed_current_states: set[str],
        worker_id: str | None = None,
        extra_fields: dict[str, Any] | None = None,
        extra_fields_factory: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Apply a worker-owned transition under canonical and ownership rules.

        Four guards must pass before any write happens: the job exists,
        the caller owns it (when ``worker_id`` is supplied), and the
        canonical transition graph permits the move from the current state.
        This is the implementation seam ADR 0010 §7 calls out for
        stale-writer rejection in a store that does not yet persist explicit
        version numbers.

        ``extra_fields`` and ``extra_fields_factory`` are mutually exclusive.
        The factory is invoked with the current job dict and its return value
        is merged into the record after the status transition is applied.
        """
        if extra_fields is not None and extra_fields_factory is not None:
            raise ValueError(
                "extra_fields and extra_fields_factory are mutually exclusive"
            )
        with self._locked_store():
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if worker_id is not None and job.get("worker_id") != worker_id:
                return None
            current = job.get("status")
            if current not in allowed_current_states:
                return None
            # A self-transition (current == target) is a metadata refresh,
            # not a true state change, so the canonical transition graph
            # only gates moves between distinct states.
            if current != target_state and not can_transition(current, target_state):
                return None
            fields = (
                extra_fields_factory(job)
                if extra_fields_factory is not None
                else (extra_fields or {})
            )
            job["status"] = target_state
            for key, value in fields.items():
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

    # --- Test scaffolding (not for production use) ---
    # These helpers bypass the canonical guarded-transition path so tests
    # can synthesize states (e.g., an already-elapsed cancel deadline) that
    # cannot be produced by replaying real API/worker calls in wall-clock
    # time. They must not be invoked from app code.
    def force_job_fields(
        self, job_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        with self._locked_store():
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                job[key] = value
            self._persist_unlocked()
            return copy.deepcopy(job)

    def force_job_record(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["job_id"])
        with self._locked_store():
            self._jobs[job_id] = copy.deepcopy(record)
            self._persist_unlocked()
            return copy.deepcopy(self._jobs[job_id])

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
