"""Canonical job lifecycle state model and transition governance.

This module is the single source of truth for canonical job states and the
legal transitions between them, per ADR 0010. Other modules must request
transitions through these helpers rather than open-coding status writes.

Canonical states:
    queued, claimed, running, cancelling, succeeded, failed, cancelled

Terminal states are immutable: succeeded, failed, cancelled.
"""

from __future__ import annotations

from typing import Any

JOB_STATE_QUEUED = "queued"
JOB_STATE_CLAIMED = "claimed"
JOB_STATE_RUNNING = "running"
JOB_STATE_CANCELLING = "cancelling"
JOB_STATE_SUCCEEDED = "succeeded"
JOB_STATE_FAILED = "failed"
JOB_STATE_CANCELLED = "cancelled"

CANONICAL_STATES = frozenset(
    {
        JOB_STATE_QUEUED,
        JOB_STATE_CLAIMED,
        JOB_STATE_RUNNING,
        JOB_STATE_CANCELLING,
        JOB_STATE_SUCCEEDED,
        JOB_STATE_FAILED,
        JOB_STATE_CANCELLED,
    }
)

TERMINAL_STATES = frozenset(
    {JOB_STATE_SUCCEEDED, JOB_STATE_FAILED, JOB_STATE_CANCELLED}
)

# In-flight states that must not survive a service restart with their original
# label — they are reconciled to a terminal `failed` outcome on restore.
INFLIGHT_STATES = frozenset(
    {JOB_STATE_QUEUED, JOB_STATE_CLAIMED, JOB_STATE_RUNNING, JOB_STATE_CANCELLING}
)

# Canonical transition graph from ADR 0010. Terminal states map to an empty
# set, enforcing terminal immutability.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    JOB_STATE_QUEUED: frozenset({JOB_STATE_CLAIMED, JOB_STATE_CANCELLED}),
    JOB_STATE_CLAIMED: frozenset(
        {JOB_STATE_RUNNING, JOB_STATE_CANCELLED, JOB_STATE_FAILED}
    ),
    JOB_STATE_RUNNING: frozenset(
        {JOB_STATE_SUCCEEDED, JOB_STATE_FAILED, JOB_STATE_CANCELLING}
    ),
    JOB_STATE_CANCELLING: frozenset({JOB_STATE_CANCELLED, JOB_STATE_FAILED}),
    JOB_STATE_SUCCEEDED: frozenset(),
    JOB_STATE_FAILED: frozenset(),
    JOB_STATE_CANCELLED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    """Return True if ``current -> target`` is a legal canonical transition."""
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


class IllegalTransitionError(ValueError):
    """Raised when a caller attempts a transition not allowed by the model."""


def apply_transition(record: dict[str, Any], target: str) -> dict[str, Any]:
    """Return a copy of ``record`` with its status moved to ``target``.

    Raises ``IllegalTransitionError`` if the transition is not permitted.
    Callers wanting silent rejection should use ``can_transition`` first.
    """
    current = record.get("status")
    if not can_transition(current, target):
        raise IllegalTransitionError(
            f"Illegal job state transition: {current!r} -> {target!r}"
        )
    updated = dict(record)
    updated["status"] = target
    return updated


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


# Legacy persisted labels we still read from disk. We never write these.
_LEGACY_COMPLETED = "completed"
_LEGACY_CANCELLATION_ERROR = "Cancelled by user"


def normalize_legacy_record(record: dict[str, Any]) -> dict[str, Any]:
    """Map legacy persisted labels to canonical states without semantic loss.

    - legacy ``completed`` becomes canonical ``succeeded``
    - legacy ``failed + error="Cancelled by user"`` becomes canonical ``cancelled``

    The returned dict is a shallow copy; the original is left untouched.
    """
    normalized = dict(record)
    status = normalized.get("status")
    error = normalized.get("error")
    if status == _LEGACY_COMPLETED:
        normalized["status"] = JOB_STATE_SUCCEEDED
    elif status == JOB_STATE_FAILED and error == _LEGACY_CANCELLATION_ERROR:
        normalized["status"] = JOB_STATE_CANCELLED
        normalized["error"] = None
    return normalized


def normalize_restored_inflight_record(
    record: dict[str, Any], finished_at: str
) -> dict[str, Any]:
    """Reconcile in-flight records found at restore time to a terminal state.

    Restore must bias uncertain in-flight work toward explicit ``failed``
    rather than fabricating a successful outcome. Legacy labels are mapped
    first so a legacy ``completed`` record is preserved as ``succeeded``.
    """
    normalized = normalize_legacy_record(record)
    restored_status = normalized.get("status")
    if restored_status in INFLIGHT_STATES:
        normalized["status"] = JOB_STATE_FAILED
        normalized["finished_at"] = normalized.get("finished_at") or finished_at
        if restored_status == JOB_STATE_CANCELLING:
            normalized["error"] = "cancel_timeout"
            normalized["error_code"] = "cancel_timeout"
        else:
            normalized["error"] = "Service restarted before the job completed"
    return normalized
