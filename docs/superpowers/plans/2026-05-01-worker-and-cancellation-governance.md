# Worker and Cancellation Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor cancellation and worker observability onto a shared worker/runtime governance model so that in-flight cancellation always converges, worker summary remains truthful, and no backend-specific cancel patching remains.

**Architecture:** Replace the current API-led `force` cancellation flow with a worker/runtime-owned cancellation contract that carries deadline metadata and finalizes terminal outcomes only from the execution side. Split worker summary into stable fleet counts versus live availability counts, and update the browser to consume the new contract directly without backward-compatibility shims.

**Tech Stack:** FastAPI, Python unittest, static browser JavaScript in `app/static/index.html`, local JSON job/worker stores, resident runtime host/provider boundary.

---

## File Structure

- Modify: `app/jobs/lifecycle.py`
  - Extend canonical lifecycle helpers to validate cancellation governance metadata and deadline-driven convergence semantics.
- Modify: `app/jobs/local.py`
  - Centralize storage mutations for cancellation intent, escalation, timeout adjudication, and worker-owned terminal finalization.
- Create: `app/cancellation.py`
  - Shared cancellation capability and runtime/worker governance helpers. This is the new platform-owned boundary instead of ad hoc `should_cancel` callback usage.
- Modify: `app/runtime_host_registration.py`
  - Replace best-effort `should_cancel` fallback plumbing with the shared cancellation capability contract.
- Modify: `app/runtime_host.py`
  - Execute runtime work through the shared cancellation context and surface stop-state signals back to the worker.
- Modify: `app/engines/panowan.py`
  - Stop open-coding cancellation callback threading; consume the shared runtime cancellation context instead.
- Modify: `app/engines/upscale.py`
  - Align upscale execution with the same shared cancellation capability shape so cancellation is backend-agnostic.
- Modify: `third_party/PanoWan/sources/runtime_provider.py`
  - Replace the current `del should_cancel` placeholder with explicit cancellation polling/checkpoint handling through the shared contract.
- Modify: `app/worker_service.py`
  - Make the worker own cancellation deadlines, timeout adjudication, slot release, reconciliation, and worker-summary reporting.
- Modify: `app/api.py`
  - Remove legacy `force` semantics, expose new cancellation request / escalation contract, and replace worker summary aggregation fields.
- Modify: `app/static/index.html`
  - Consume the new cancellation contract and new worker summary fields directly; add retry/escalation UI for `cancelling` without compatibility aliasing.
- Modify: `tests/test_jobs.py`
  - Add storage/lifecycle tests for deadline metadata, escalation, and timeout finalization.
- Modify: `tests/test_worker_service.py`
  - Add worker-owned convergence, reconciliation, occupancy release, and runtime-capability tests.
- Modify: `tests/test_api.py`
  - Replace `force`-based expectations with the new request/escalation API contract and worker summary payload shape.
- Modify: `tests/test_static_ui.py`
  - Lock timeout-aware `cancelling` UI, retry/escalation actions, and the split worker summary view.

### Task 1: Introduce the shared cancellation governance module

**Files:**
- Create: `app/cancellation.py`
- Modify: `tests/test_jobs.py`
- Modify: `app/jobs/lifecycle.py`

- [ ] **Step 1: Write the failing tests for cancellation metadata and capability defaults**

```python
from datetime import UTC, datetime, timedelta
import unittest

from app.cancellation import (
    CancellationCapability,
    CancellationContext,
    begin_cancellation,
    escalate_cancellation,
)


class CancellationGovernanceTests(unittest.TestCase):
    def test_begin_cancellation_adds_deadline_metadata(self) -> None:
        now = datetime(2026, 5, 1, 22, 5, tzinfo=UTC)
        capability = CancellationCapability(
            supports_soft_cancel=True,
            supports_escalated_cancel=True,
            default_cancel_timeout_sec=45,
            cancel_poll_interval_sec=1,
            cancel_checkpoint_granularity="checkpoint",
        )

        record = begin_cancellation(
            {
                "job_id": "job-1",
                "status": "running",
            },
            capability=capability,
            now=now,
        )

        self.assertEqual(record["status"], "cancelling")
        self.assertEqual(record["cancel_mode"], "soft")
        self.assertEqual(record["cancel_attempt"], 1)
        self.assertEqual(record["cancel_requested_at"], now.isoformat())
        self.assertEqual(
            record["cancel_deadline_at"],
            (now + timedelta(seconds=45)).isoformat(),
        )

    def test_escalate_cancellation_increments_attempt_and_mode(self) -> None:
        now = datetime(2026, 5, 1, 22, 6, tzinfo=UTC)
        capability = CancellationCapability(
            supports_soft_cancel=True,
            supports_escalated_cancel=True,
            default_cancel_timeout_sec=30,
            cancel_poll_interval_sec=1,
            cancel_checkpoint_granularity="checkpoint",
        )
        record = {
            "job_id": "job-1",
            "status": "cancelling",
            "cancel_mode": "soft",
            "cancel_attempt": 1,
            "cancel_requested_at": now.isoformat(),
            "cancel_deadline_at": (now + timedelta(seconds=30)).isoformat(),
        }

        escalated = escalate_cancellation(
            record,
            capability=capability,
            now=now + timedelta(seconds=10),
        )

        self.assertEqual(escalated["cancel_mode"], "escalated")
        self.assertEqual(escalated["cancel_attempt"], 2)
        self.assertGreater(
            escalated["cancel_deadline_at"],
            record["cancel_deadline_at"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_jobs.CancellationGovernanceTests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cancellation'`

- [ ] **Step 3: Write the shared cancellation module and lifecycle helpers**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_jobs.CancellationGovernanceTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/cancellation.py app/jobs/lifecycle.py tests/test_jobs.py && rtk git commit -m "refactor: add shared cancellation governance primitives"
```

### Task 2: Refactor job storage onto cancellation intent and timeout finalization

**Files:**
- Modify: `app/jobs/local.py`
- Modify: `app/jobs/lifecycle.py`
- Modify: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing storage tests for request, escalate, and timeout adjudication**

```python
class LocalJobCancellationFlowTests(unittest.TestCase):
    def test_request_cancellation_sets_deadline_metadata(self) -> None:
        backend = self.make_backend()
        job = backend.create_job({"prompt": "p"})
        claimed = backend.claim_next_job(worker_id="worker-1")
        backend.mark_running(job["job_id"], "worker-1")

        result = backend.request_cancellation(job["job_id"], worker_id="worker-1")

        self.assertEqual(result["status"], "cancelling")
        self.assertEqual(result["cancel_mode"], "soft")
        self.assertIn("cancel_requested_at", result)
        self.assertIn("cancel_deadline_at", result)

    def test_escalate_cancellation_replaces_legacy_force_behavior(self) -> None:
        backend = self.make_backend()
        job = self.make_running_job(backend, worker_id="worker-1")
        backend.request_cancellation(job["job_id"], worker_id="worker-1")

        result = backend.escalate_cancellation(job["job_id"], worker_id="worker-1")

        self.assertEqual(result["status"], "cancelling")
        self.assertEqual(result["cancel_mode"], "escalated")
        self.assertEqual(result["cancel_attempt"], 2)

    def test_finalize_cancel_timeout_marks_failed(self) -> None:
        backend = self.make_backend()
        job = self.make_running_job(backend, worker_id="worker-1")
        cancelling = backend.request_cancellation(job["job_id"], worker_id="worker-1")

        result = backend.finalize_cancellation_timeout(
            cancelling["job_id"],
            worker_id="worker-1",
            reason="cancel_timeout",
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "cancel_timeout")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_jobs.LocalJobCancellationFlowTests -v`
Expected: FAIL with `AttributeError` for `escalate_cancellation` / `finalize_cancellation_timeout`

- [ ] **Step 3: Implement storage entrypoints and remove the old force-oriented path**

```python
def request_cancellation(self, job_id: str, *, worker_id: str | None = None) -> dict[str, Any] | None:
    def mutate(job: dict[str, Any]) -> dict[str, Any] | None:
        status = job.get("status")
        if status == "queued":
            return self._apply_terminal_cancel(job)
        if status not in {"claimed", "running"}:
            return None
        if worker_id is not None and job.get("worker_id") != worker_id:
            return None
        capability = self._cancellation_capability_for_job(job)
        return begin_cancellation(job, capability=capability, now=self._utcnow())

    return self._update_job(job_id, mutate)


def escalate_cancellation(self, job_id: str, *, worker_id: str | None = None) -> dict[str, Any] | None:
    def mutate(job: dict[str, Any]) -> dict[str, Any] | None:
        if job.get("status") != "cancelling":
            return None
        if worker_id is not None and job.get("worker_id") != worker_id:
            return None
        capability = self._cancellation_capability_for_job(job)
        return escalate_cancellation(job, capability=capability, now=self._utcnow())

    return self._update_job(job_id, mutate)


def finalize_cancellation_timeout(
    self,
    job_id: str,
    *,
    worker_id: str,
    reason: str,
) -> dict[str, Any] | None:
    def mutate(job: dict[str, Any]) -> dict[str, Any] | None:
        if job.get("status") != "cancelling":
            return None
        if job.get("worker_id") != worker_id:
            return None
        return self._mark_failed_record(job, worker_id=worker_id, error=str(reason), error_code=reason)

    return self._update_job(job_id, mutate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_jobs.LocalJobCancellationFlowTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/jobs/local.py app/jobs/lifecycle.py tests/test_jobs.py && rtk git commit -m "refactor: route cancellation storage through governance entrypoints"
```

### Task 3: Move runtime host and engines onto the shared cancellation contract

**Files:**
- Modify: `app/runtime_host_registration.py`
- Modify: `app/runtime_host.py`
- Modify: `app/engines/panowan.py`
- Modify: `app/engines/upscale.py`
- Modify: `app/process_runner.py`
- Modify: `third_party/PanoWan/sources/runtime_provider.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing runtime contract tests**

```python
class RuntimeCancellationContractTests(unittest.TestCase):
    def test_panowan_engine_passes_cancellation_context_to_host(self) -> None:
        host = FakeHost()
        engine = PanoWanEngine(host)
        job = {
            "job_id": "job-1",
            "type": "generate",
            "prompt": "demo",
            "worker_id": "worker-1",
            "cancel_mode": "soft",
            "cancel_attempt": 1,
            "cancel_requested_at": "2026-05-01T14:00:00+00:00",
            "cancel_deadline_at": "2026-05-01T14:00:45+00:00",
            "_cancellation_context": lambda: CancellationContext(
                job_id="job-1",
                worker_id="worker-1",
                mode="soft",
                requested_at="2026-05-01T14:00:00+00:00",
                deadline_at="2026-05-01T14:00:45+00:00",
                attempt=1,
            ),
        }

        engine.run(job)

        self.assertEqual(host.last_context.mode, "soft")
        self.assertEqual(host.last_context.deadline_at, "2026-05-01T14:00:45+00:00")

    def test_runtime_provider_observes_cancel_context_instead_of_discarding_it(self) -> None:
        provider = FakeResidentProvider(stop_after_checks=2)
        result = provider.run_job_inprocess(
            loaded={"pipeline": object()},
            job={"prompt": "demo", "output_path": "out.mp4", "task": "t2v", "resolution": {"width": 2048, "height": 1024}},
            cancellation=FakeCancellationProbe([False, True]),
        )

        self.assertEqual(result["status"], "cancelled")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_worker_service.RuntimeCancellationContractTests -v`
Expected: FAIL because engines/providers still expect `should_cancel`

- [ ] **Step 3: Replace `should_cancel` plumbing with shared cancellation context objects**

```python
class RuntimeCancellationProbe(Protocol):
    def context(self) -> CancellationContext | None:
        raise NotImplementedError

    def should_stop(self) -> bool:
        raise NotImplementedError

    def checkpoint(self, label: str) -> str:
        raise NotImplementedError


def run_job(
    self,
    provider_key: str,
    job: Mapping[str, object],
    *,
    cancellation: RuntimeCancellationProbe | None = None,
) -> dict[str, object]:
    provider = self._providers[provider_key]
    loaded = self._ensure_loaded(provider_key, job)
    return provider.execute(loaded, job, cancellation=cancellation)
```

```python
def run(self, job: Mapping[str, object]) -> EngineResult:
    raw = dict(job)
    result = self._host.run_job(
        self.provider_key,
        runner_payload,
        cancellation=raw.get("_cancellation_context")() if callable(raw.get("_cancellation_context")) else None,
    )
    if result.get("status") == "cancelled":
        raise RuntimeError("cancelled_by_runtime")
```

```python
def run_job_inprocess(
    loaded: dict[str, Any],
    job: Mapping[str, Any],
    *,
    cancellation: Any = None,
) -> dict[str, Any]:
    payload = validate_job(dict(job))
    if cancellation is not None and cancellation.should_stop():
        return {"status": "cancelled", "output_path": payload["output_path"]}
    video = pipe(**pipe_kwargs)
    if cancellation is not None and cancellation.should_stop():
        return {"status": "cancelled", "output_path": payload["output_path"]}
    save_video(video, output_path, fps=15, quality=10, ffmpeg_params=["-crf", "18"])
    return {"status": "ok", "output_path": output_path}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_worker_service.RuntimeCancellationContractTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/runtime_host_registration.py app/runtime_host.py app/engines/panowan.py app/engines/upscale.py app/process_runner.py third_party/PanoWan/sources/runtime_provider.py tests/test_worker_service.py && rtk git commit -m "refactor: move runtimes to shared cancellation contract"
```

### Task 4: Make worker lifecycle own cancellation deadlines, timeout adjudication, and reconciliation

**Files:**
- Modify: `app/worker_service.py`
- Modify: `tests/test_worker_service.py`
- Modify: `app/jobs/local.py`

- [ ] **Step 1: Write the failing worker lifecycle tests**

```python
class WorkerCancellationGovernanceTests(unittest.TestCase):
    def test_worker_times_out_cancelling_job_to_failed(self) -> None:
        backend = self.make_backend()
        registry = self.make_registry()
        host = self.make_host()
        worker_id = "worker-1"
        job = self.make_running_job(backend, worker_id=worker_id)
        backend.request_cancellation(job["job_id"], worker_id=worker_id)
        backend.force_job_fields(
            job["job_id"],
            cancel_deadline_at="2026-05-01T13:59:00+00:00",
        )

        reconciled = reconcile_overdue_cancellations(backend, worker_id=worker_id)

        self.assertEqual(reconciled[0]["status"], "failed")
        self.assertEqual(reconciled[0]["error_code"], "cancel_timeout")

    def test_worker_releases_occupancy_when_runtime_confirms_cancel(self) -> None:
        backend = self.make_backend()
        worker_store = self.make_worker_store()
        worker_id = "worker-1"
        self.make_running_job(backend, worker_id=worker_id)

        finalize_runtime_cancellation(
            backend,
            worker_store,
            job_id="job-1",
            worker_id=worker_id,
        )

        summary = worker_store.get_worker(worker_id)
        self.assertEqual(summary["running_jobs"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_worker_service.WorkerCancellationGovernanceTests -v`
Expected: FAIL with missing reconciliation/finalization helpers

- [ ] **Step 3: Implement worker-owned reconciliation and finalization helpers**

```python
def reconcile_overdue_cancellations(
    backend: LocalJobBackend,
    *,
    worker_id: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    now = now or datetime.now(UTC)
    reconciled: list[dict[str, object]] = []
    for job in backend.list_jobs():
        if job.get("status") != "cancelling":
            continue
        if worker_id is not None and job.get("worker_id") != worker_id:
            continue
        deadline_at = datetime.fromisoformat(str(job["cancel_deadline_at"]))
        if deadline_at > now:
            continue
        result = backend.finalize_cancellation_timeout(
            str(job["job_id"]),
            worker_id=str(job["worker_id"]),
            reason="cancel_timeout",
        )
        if result is not None:
            reconciled.append(result)
    return reconciled


def finalize_runtime_cancellation(
    backend: LocalJobBackend,
    worker_registry: LocalWorkerRegistry,
    *,
    job_id: str,
    worker_id: str,
) -> dict[str, object] | None:
    result = backend.request_cancellation(job_id, worker_id=worker_id, finished=True)
    if result is not None:
        worker_registry.upsert_worker(worker_id, {"running_jobs": 0})
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_worker_service.WorkerCancellationGovernanceTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/worker_service.py app/jobs/local.py tests/test_worker_service.py && rtk git commit -m "refactor: make worker own cancellation convergence"
```

### Task 5: Replace worker summary aggregation with stable fleet counts and cancellation drag visibility

**Files:**
- Modify: `app/api.py`
- Modify: `app/worker_service.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing worker summary tests**

```python
class WorkerSummaryContractTests(unittest.TestCase):
    def test_summary_keeps_known_workers_when_all_are_stale(self) -> None:
        self.worker_registry.upsert_worker("worker-1", {"status": "online", "running_jobs": 0, "max_concurrent_jobs": 1})
        self.worker_registry.upsert_worker("worker-2", {"status": "online", "running_jobs": 1, "max_concurrent_jobs": 1})

        summary = api._worker_summary()

        self.assertEqual(summary["known_workers"], 2)
        self.assertEqual(summary["online_workers"], 0)

    def test_summary_reports_stuck_cancelling_workers_separately(self) -> None:
        self.backend.create_job({"prompt": "demo"})
        self.backend.force_job_record({
            "job_id": "job-1",
            "status": "cancelling",
            "worker_id": "worker-2",
            "cancel_deadline_at": "2026-05-01T14:30:00+00:00",
        })

        summary = api._worker_summary()

        self.assertEqual(summary["cancelling_jobs"], 1)
        self.assertEqual(summary["stuck_cancelling_workers"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_api.WorkerSummaryContractTests -v`
Expected: FAIL because the summary still returns `total_workers` and merges stale/busy signals

- [ ] **Step 3: Rewrite summary aggregation instead of extending the old payload**

```python
def _worker_summary() -> dict[str, Any]:
    jobs = get_job_backend().list_jobs()
    registry = get_worker_registry()
    known_workers = registry.list_workers(stale_seconds=None)
    online_workers = registry.list_workers(stale_seconds=settings.worker_stale_seconds)
    online_ids = {str(worker.get("worker_id")) for worker in online_workers}
    cancelling_by_worker = {
        str(job.get("worker_id"))
        for job in jobs
        if job.get("status") == "cancelling" and job.get("worker_id")
    }
    busy_ids = {
        str(worker.get("worker_id"))
        for worker in online_workers
        if int(worker.get("running_jobs") or 0) > 0
    }
    total_capacity = sum(int(worker.get("max_concurrent_jobs") or 0) for worker in online_workers)
    occupied_capacity = sum(int(worker.get("running_jobs") or 0) for worker in online_workers)
    return {
        "known_workers": len(known_workers),
        "online_workers": len(online_workers),
        "busy_workers": len(busy_ids),
        "stuck_cancelling_workers": len(cancelling_by_worker & online_ids),
        "queued_jobs": sum(1 for job in jobs if job.get("status") in {"queued", "claimed"}),
        "running_jobs": sum(1 for job in jobs if job.get("status") == "running"),
        "cancelling_jobs": sum(1 for job in jobs if job.get("status") == "cancelling"),
        "total_capacity": total_capacity,
        "occupied_capacity": occupied_capacity,
        "effective_available_capacity": max(total_capacity - occupied_capacity, 0),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_api.WorkerSummaryContractTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/api.py app/worker_service.py tests/test_api.py tests/test_worker_service.py && rtk git commit -m "refactor: replace worker summary with fleet governance metrics"
```

### Task 6: Replace the public cancel API with explicit request and escalation semantics

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing API contract tests**

```python
class CancelApiContractTests(unittest.TestCase):
    def test_cancel_running_job_returns_cancelling_without_force_flag(self) -> None:
        job = self.make_running_job(worker_id="worker-1")

        response = self.client.post(f"/jobs/{job['job_id']}/cancel", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "cancelling")
        self.assertEqual(payload["cancel_mode"], "soft")
        self.assertNotIn("warning", payload)

    def test_escalate_endpoint_updates_cancel_mode(self) -> None:
        job = self.make_cancelling_job(worker_id="worker-1")

        response = self.client.post(f"/jobs/{job['job_id']}/cancel/escalate", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "cancelling")
        self.assertEqual(payload["cancel_mode"], "escalated")
        self.assertEqual(payload["cancel_attempt"], 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_api.CancelApiContractTests -v`
Expected: FAIL because `/cancel` still expects `force` behavior and `/cancel/escalate` does not exist

- [ ] **Step 3: Replace the legacy API surface instead of layering aliases**

```python
def cancel_job(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job["status"]
    if status == "queued":
        cancelled = get_job_backend().cancel_queued_job(job_id)
        if cancelled:
            current = _get_job(job_id)
            broadcast_job_event("job_updated", current)
            return current
    if status in {"claimed", "running"}:
        result = get_job_backend().request_cancellation(job_id, worker_id=job.get("worker_id"))
        if result is None:
            raise HTTPException(status_code=409, detail=f"Cannot cancel job with status {status}")
        broadcast_job_event("job_updated", result)
        return result
    if status == "cancelling":
        return job
    raise HTTPException(status_code=409, detail=f"Cannot cancel job with status {status}")


@app.post("/jobs/{job_id}/cancel/escalate")
def escalate_cancel_job_endpoint(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result = get_job_backend().escalate_cancellation(job_id, worker_id=job.get("worker_id"))
    if result is None:
        raise HTTPException(status_code=409, detail="Job is not in cancelling state")
    broadcast_job_event("job_updated", result)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_api.CancelApiContractTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/api.py tests/test_api.py && rtk git commit -m "refactor: replace force cancel api with request and escalation flows"
```

### Task 7: Refactor the browser to consume the new cancellation and worker summary contract directly

**Files:**
- Modify: `app/static/index.html`
- Modify: `tests/test_static_ui.py`

- [ ] **Step 1: Write the failing browser contract tests**

```python
class StaticUiCancellationGovernanceTests(unittest.TestCase):
    def test_worker_summary_uses_known_workers_and_stuck_cancelling_fields(self) -> None:
        html = self.read_static_html()
        self.assertIn('summary.known_workers', html)
        self.assertIn('summary.stuck_cancelling_workers', html)
        self.assertNotIn('summary.total_workers', html)

    def test_cancelling_action_cell_exposes_retry_and_escalation(self) -> None:
        html = self.read_static_html()
        self.assertIn('data-action="retry-cancel"', html)
        self.assertIn('data-action="escalate-cancel"', html)
        self.assertNotIn('force: isRunning', html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk test python -m unittest tests.test_static_ui.StaticUiCancellationGovernanceTests -v`
Expected: FAIL because the browser still posts `{ force: isRunning }` and still reads `summary.total_workers`

- [ ] **Step 3: Rewrite the browser cancellation and summary UI against the new contract**

```javascript
async function cancelJob(jobId) {
  const res = await fetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
  _jobCache[payload.job_id] = payload;
  sseClient._renderIncremental();
}

async function escalateCancel(jobId) {
  const res = await fetch(`/jobs/${jobId}/cancel/escalate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.detail || `HTTP ${res.status}`);
  _jobCache[payload.job_id] = payload;
  sseClient._renderIncremental();
}

function actionCell(job) {
  if (job.status === "cancelling") {
    return `
      <span class="action-buttons">
        <span class="badge badge-running">正在取消…</span>
        <button class="preview-btn" data-action="retry-cancel" data-job-id="${escapeHtml(job.job_id)}">重试取消</button>
        <button class="preview-btn" data-action="escalate-cancel" data-job-id="${escapeHtml(job.job_id)}" style="background:var(--error-soft);color:var(--error);">确认强制取消</button>
      </span>
    `;
  }
}

async function refreshWorkerSummary() {
  const res = await fetch("/workers/summary");
  const summary = await res.json();
  document.getElementById("workers-total").textContent = String(summary.known_workers ?? "-");
  document.getElementById("workers-online").textContent = String(summary.online_workers ?? "-");
  document.getElementById("workers-busy").textContent = String(summary.busy_workers ?? "-");
  document.getElementById("jobs-queued").textContent = String(summary.queued_jobs ?? "-");
  document.getElementById("jobs-running").textContent = String(summary.running_jobs ?? "-");
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk test python -m unittest tests.test_static_ui.StaticUiCancellationGovernanceTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/static/index.html tests/test_static_ui.py && rtk git commit -m "refactor: align browser with cancellation governance contract"
```

### Task 8: Lock the end-to-end governance model with focused regression suites

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_jobs.py`
- Modify: `tests/test_static_ui.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Add the final regression tests for the main races and stale-worker recovery**

```python
class CancellationGovernanceRegressionTests(unittest.TestCase):
    def test_completion_wins_if_engine_finishes_before_cancel_converges(self) -> None:
        backend = self.make_backend()
        worker_id = "worker-1"
        job = self.make_running_job(backend, worker_id=worker_id)
        backend.request_cancellation(job["job_id"], worker_id=worker_id)

        result = backend.mark_succeeded(job["job_id"], worker_id, "out.mp4")
        current = backend.get_job(job["job_id"])

        self.assertIsNotNone(result)
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["output_path"], "out.mp4")

    def test_worker_loss_during_cancelling_converges_to_failed(self) -> None:
        backend = self.make_backend()
        worker_id = "worker-1"
        job = self.make_running_job(backend, worker_id=worker_id)
        cancelling = backend.request_cancellation(job["job_id"], worker_id=worker_id)
        backend.force_job_fields(
            job["job_id"],
            cancel_deadline_at="2026-05-01T13:59:00+00:00",
            worker_id=worker_id,
        )

        reconciled = reconcile_overdue_cancellations(backend, worker_id=worker_id)
        current = backend.get_job(job["job_id"])

        self.assertEqual(reconciled[0]["status"], "failed")
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["error_code"], "cancel_timeout")
        self.assertEqual(cancelling["status"], "cancelling")

    def test_terminal_state_cannot_be_overwritten_by_late_runtime_callback(self) -> None:
        backend = self.make_backend()
        worker_id = "worker-1"
        job = self.make_running_job(backend, worker_id=worker_id)
        backend.request_cancellation(job["job_id"], worker_id=worker_id)
        backend.finalize_cancellation_timeout(
            job["job_id"],
            worker_id=worker_id,
            reason="cancel_timeout",
        )

        late = backend.mark_succeeded(job["job_id"], worker_id, "late.mp4")
        current = backend.get_job(job["job_id"])

        self.assertIsNone(late)
        self.assertEqual(current["status"], "failed")
        self.assertNotEqual(current.get("output_path"), "late.mp4")
```

```python
class WorkerSummaryRegressionTests(unittest.TestCase):
    def test_zero_online_workers_does_not_mean_zero_known_workers(self) -> None:
        self.worker_registry.upsert_worker(
            "worker-1",
            {"status": "online", "running_jobs": 0, "max_concurrent_jobs": 1},
        )
        self.worker_registry.upsert_worker(
            "worker-2",
            {"status": "online", "running_jobs": 0, "max_concurrent_jobs": 1},
        )

        summary = api._worker_summary()

        self.assertEqual(summary["known_workers"], 2)
        self.assertEqual(summary["online_workers"], 0)

    def test_cancellation_drag_reduces_effective_available_capacity(self) -> None:
        self.worker_registry.upsert_worker(
            "worker-1",
            {"status": "online", "running_jobs": 1, "max_concurrent_jobs": 2},
        )
        self.backend.force_job_record(
            {
                "job_id": "job-1",
                "status": "cancelling",
                "worker_id": "worker-1",
            }
        )

        summary = api._worker_summary()

        self.assertEqual(summary["busy_workers"], 1)
        self.assertEqual(summary["stuck_cancelling_workers"], 1)
        self.assertEqual(summary["effective_available_capacity"], 1)
```

- [ ] **Step 2: Run the focused suites**

Run: `rtk test python -m unittest tests.test_jobs tests.test_worker_service tests.test_api tests.test_static_ui -v`
Expected: PASS

- [ ] **Step 3: Run the full regression suite**

Run: `rtk test python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
rtk git add tests/test_api.py tests/test_jobs.py tests/test_static_ui.py tests/test_worker_service.py && rtk git commit -m "test: lock worker and cancellation governance regressions"
```

## Self-Review

- Spec coverage check:
  - Shared cancellation capability: Tasks 1, 3
  - Worker-owned timeout adjudication: Tasks 2, 4
  - Worker summary contract rewrite: Task 5
  - API/UI cancellation contract rewrite: Tasks 6, 7
  - Resilience / stale worker / timeout recovery: Tasks 4, 8
- Placeholder scan:
  - No `TBD`, `TODO`, `...`, or “similar to” placeholders remain in the implementation tasks.
  - Code examples use explicit method bodies or concrete assertions throughout the plan.
- Type consistency:
  - Shared names are consistent across tasks: `CancellationCapability`, `CancellationContext`, `request_cancellation`, `escalate_cancellation`, `finalize_cancellation_timeout`, `known_workers`, `stuck_cancelling_workers`.
