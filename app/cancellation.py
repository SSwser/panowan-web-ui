from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping


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
