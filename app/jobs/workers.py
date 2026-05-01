import copy
import json
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class LocalWorkerRegistry:
    def __init__(self, worker_store_path: str):
        self.worker_store_path = worker_store_path
        self._lock = threading.Lock()
        self._lock_path = f"{worker_store_path}.lock"
        self._workers: dict[str, dict[str, Any]] = {}
        self._load_from_disk()

    def upsert_worker(self, worker_id: str, record: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_worker(worker_id, record)
        with self._locked_store():
            self._workers[worker_id] = normalized
            self._persist_unlocked()
            return copy.deepcopy(normalized)

    def adjust_running_jobs(self, worker_id: str, delta: int) -> dict[str, Any] | None:
        """Atomically nudge running_jobs by ``delta``, clamped at zero.

        Used when occupancy changes outside the heartbeat path. Going through a
        delta keeps the call correct for workers that run multiple jobs
        concurrently — releasing one slot must not zero the counter.
        """
        with self._locked_store():
            existing = self._workers.get(worker_id)
            if existing is None:
                return None
            existing["running_jobs"] = max(0, int(existing.get("running_jobs", 0)) + int(delta))
            existing["last_seen"] = now_iso()
            self._persist_unlocked()
            return copy.deepcopy(existing)

    def list_workers(self, stale_seconds: float | None = None) -> list[dict[str, Any]]:
        with self._locked_store():
            workers = [copy.deepcopy(worker) for worker in self._workers.values()]
        if stale_seconds is None:
            return workers
        now = datetime.now(UTC)
        return [
            worker
            for worker in workers
            if _is_fresh(worker.get("last_seen"), now=now, stale_seconds=stale_seconds)
        ]

    def has_upscale_model(self, model_name: str, stale_seconds: float) -> bool:
        return any(
            worker.get("status") == "online"
            and model_name in worker.get("available_upscale_models", [])
            for worker in self.list_workers(stale_seconds=stale_seconds)
        )

    def _normalize_worker(self, worker_id: str, record: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(record)
        normalized["worker_id"] = worker_id
        normalized.setdefault("status", "online")
        normalized.setdefault("capabilities", [])
        normalized.setdefault("available_upscale_models", [])
        normalized.setdefault("max_concurrent_jobs", 1)
        normalized.setdefault("running_jobs", 0)
        normalized["last_seen"] = now_iso()
        return normalized

    def _load_from_disk(self) -> None:
        with self._locked_store():
            return

    def _persist_unlocked(self) -> None:
        _ensure_parent_dir(self.worker_store_path)
        temp_path = f"{self.worker_store_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"workers": self._workers}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, self.worker_store_path)

    def _load_workers_unlocked(self) -> None:
        if not os.path.isfile(self.worker_store_path):
            self._workers = {}
            return
        with open(self.worker_store_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_workers = payload.get("workers", payload)
        if not isinstance(raw_workers, dict):
            raise ValueError("Worker registry payload must contain a workers object")
        self._workers = {
            str(worker_id): record
            for worker_id, record in raw_workers.items()
            if isinstance(record, dict)
        }

    def _locked_store(self) -> "_StoreLock":
        return _StoreLock(self)


class _StoreLock:
    def __init__(self, registry: LocalWorkerRegistry):
        self._registry = registry
        self._handle = None

    def __enter__(self) -> "_StoreLock":
        self._registry._lock.acquire()
        _ensure_parent_dir(self._registry._lock_path)
        self._handle = open(self._registry._lock_path, "a+b")
        _prepare_lock_file(self._handle)
        _acquire_file_lock(self._handle)
        self._registry._load_workers_unlocked()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._handle is not None:
                _release_file_lock(self._handle)
                self._handle.close()
        finally:
            self._registry._lock.release()


def _is_fresh(value: str | None, now: datetime, stale_seconds: float) -> bool:
    last_seen = parse_iso(value or "")
    if last_seen is None:
        return False
    return (now - last_seen).total_seconds() <= stale_seconds


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
