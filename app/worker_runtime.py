"""Worker-local PanoWan runtime controller.

Owns the state machine for one long-lived pipeline resident on this worker.
States: cold → loading → warm → running → (warm | failed)
        warm → evicting → cold

Responsibilities that stay here:
  - Identity comparison (when to reload vs. reuse)
  - State transitions and invariants
  - Eviction timing

Responsibilities that do NOT belong here:
  - What "loading" means for PanoWan (lives in sources/runtime_adapter.py)
  - Job validation (lives in sources/runtime_adapter.py)
  - Queue semantics (lives in worker_service.py)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any


@dataclass
class _LoadedRuntime:
    identity: Any
    pipeline: Any
    last_used_at: float


class PanoWanRuntimeController:
    def __init__(
        self,
        *,
        load_fn: Callable[[Any], Any],
        teardown_fn: Callable[[Any], None],
    ) -> None:
        self._load_fn = load_fn
        self._teardown_fn = teardown_fn
        self._state: str = "cold"
        self._loaded: _LoadedRuntime | None = None

    def status_snapshot(self) -> dict:
        snap: dict = {"status": self._state}
        if self._loaded is not None:
            snap["last_used_at"] = self._loaded.last_used_at
        return snap

    def ensure_loaded(self, identity: Any) -> None:
        """Load the pipeline for *identity* if not already warm with that identity."""
        if self._state == "warm" and self._loaded is not None:
            if self._loaded.identity == identity:
                return
            self._evict_current()
        self._state = "loading"
        pipeline = self._load_fn(identity)
        self._loaded = _LoadedRuntime(
            identity=identity, pipeline=pipeline, last_used_at=monotonic()
        )
        self._state = "warm"

    def run_job(
        self,
        job: dict,
        *,
        identity: Any,
        execute_fn: Callable[[Any, dict], dict],
        is_runtime_corrupting: Callable[[Exception], bool] | None = None,
    ) -> dict:
        """Execute *job* against the resident pipeline, reloading on identity change."""
        self.ensure_loaded(identity)
        assert self._loaded is not None
        self._state = "running"
        try:
            result = execute_fn(self._loaded.pipeline, job)
            self._loaded.last_used_at = monotonic()
            self._state = "warm"
            return result
        except Exception as exc:
            corrupting = (
                is_runtime_corrupting(exc) if is_runtime_corrupting else False
            )
            if corrupting:
                # GPU state is unrecoverable; mark failed so the next call reloads.
                self._loaded = None
                self._state = "failed"
            else:
                # Job-level error only; pipeline is still usable.
                self._loaded.last_used_at = monotonic()
                self._state = "warm"
            raise

    def evict(self) -> None:
        """Tear down the loaded pipeline and return to cold state."""
        if self._loaded is not None:
            self._evict_current()

    def reset(self) -> None:
        """Clear failed state so the next ensure_loaded() can try again."""
        if self._state == "failed":
            self._loaded = None
            self._state = "cold"

    def _evict_current(self) -> None:
        self._state = "evicting"
        if self._loaded is not None:
            self._teardown_fn(self._loaded.pipeline)
        self._loaded = None
        self._state = "cold"
