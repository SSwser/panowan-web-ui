from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CancellationCapability:
    supports_soft_cancel: bool
    supports_escalated_cancel: bool
    default_cancel_timeout_sec: int
    cancel_poll_interval_sec: int
    cancel_checkpoint_granularity: str


@dataclass(frozen=True)
class CancellationContext:
    job_id: str
    worker_id: str
    mode: str
    requested_at: str
    deadline_at: str
    attempt: int


@runtime_checkable
class RuntimeCancellationProbe(Protocol):
    """Worker-supplied cancellation handle visible to runtime providers.

    Providers should poll ``should_stop_now()`` at safe checkpoint boundaries
    and may consult ``context`` to read cancel mode/deadline metadata.
    """

    @property
    def context(self) -> CancellationContext: ...
    @property
    def mode(self) -> str: ...
    @property
    def attempt(self) -> int: ...
    @property
    def deadline_at(self) -> str | None: ...
    def should_stop_now(self) -> bool: ...
    def should_escalate(self) -> bool: ...
    def checkpoint(self, label: str) -> str: ...


@dataclass(frozen=True)
class CallbackCancellationProbe:
    """Concrete probe backed by a worker-supplied callable + context."""

    context: CancellationContext
    stop_check: Callable[[], bool]

    @property
    def mode(self) -> str:
        return self.context.mode

    @property
    def attempt(self) -> int:
        return self.context.attempt

    @property
    def deadline_at(self) -> str | None:
        return self.context.deadline_at or None

    def should_stop_now(self) -> bool:
        return bool(self.stop_check())

    def should_escalate(self) -> bool:
        return self.mode == "escalated"

    def checkpoint(self, label: str) -> str:
        # Default no-op checkpoint reporter; richer reporting can layer on later.
        return label


def _iso(now: datetime) -> str:
    return now.astimezone(UTC).isoformat()


def begin_cancellation(
    job: Mapping[str, Any],
    *,
    capability: CancellationCapability,
    now: datetime,
) -> dict[str, Any]:
    requested_at = _iso(now)
    deadline_at = _iso(now + timedelta(seconds=capability.default_cancel_timeout_sec))
    return {
        **job,
        "status": "cancelling",
        "cancel_mode": "soft",
        "cancel_attempt": 1,
        "cancel_requested_at": requested_at,
        "cancel_deadline_at": deadline_at,
    }


def escalate_cancellation(
    job: Mapping[str, Any],
    *,
    capability: CancellationCapability,
    now: datetime,
) -> dict[str, Any]:
    requested_at = _iso(now)
    deadline_at = _iso(now + timedelta(seconds=capability.default_cancel_timeout_sec))
    return {
        **job,
        "cancel_mode": "escalated",
        "cancel_attempt": int(job.get("cancel_attempt") or 0) + 1,
        "cancel_requested_at": requested_at,
        "cancel_deadline_at": deadline_at,
    }
