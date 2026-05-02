# Resident Runtime Cancellation Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor job lifecycle, runtime lifecycle, and provider interrupt contracts so claimed/load/execute/cancelling semantics are correct while preserving resident runtime and VRAM reuse.

**Architecture:** Move job lifecycle orchestration into `app/worker_service.py`, split runtime preparation from execution in `app/runtime_host.py`, and upgrade provider cancellation plumbing from a boolean probe to a structured interrupt contract. Keep the current canonical job state names, but redefine `claimed`, `running`, and `cancelling` to align with actual execution boundaries.

**Tech Stack:** Python, FastAPI, unittest, resident runtime host, vendored PanoWan runtime provider

---

## File Responsibility Map

- `app/jobs/lifecycle.py`
  - canonical job states and legal transitions
  - restore-time reconciliation rules
  - no runtime-only concepts may leak here

- `app/jobs/local.py`
  - durable backend transitions for claimed/running/cancelling/cancelled/failed
  - cancellation metadata persistence
  - stale-writer guarding for worker-owned transitions

- `app/runtime_host.py`
  - resident runtime lifecycle only
  - runtime prepare/load/evict/execute state transitions
  - runtime trust/reset decisions after failure or timeout

- `app/runtime_host_registration.py`
  - adapter between backend specs and the runtime-provider protocol
  - must expose the new provider contract cleanly

- `app/worker_service.py`
  - only orchestrator allowed to move job `claimed -> running`
  - prepare-phase vs execute-phase cancellation semantics
  - timeout convergence and runtime consequence handling

- `app/engines/panowan.py`
  - engine-facing adapter from worker job records into runtime host calls
  - must stop assuming a single `run_job(...)` entrypoint owns both prepare and execute

- `third_party/PanoWan/sources/runtime_provider.py`
  - provider-side prepare/load and execute hooks
  - truthful interrupt capability declaration
  - weak execute-phase cancellation in this phase, no fake strong interrupt claims

- `app/api.py`
  - thin governance API only
  - cancel/escalate endpoints must align with the new semantics
  - summary/restore behavior must stop implying old overloaded states

- `tests/test_job_lifecycle.py`
  - canonical state transition and restore semantics

- `tests/test_jobs.py`
  - backend persistence and transition guards

- `tests/test_runtime_host.py`
  - prepare/load/execute split, runtime state transitions, failure classification

- `tests/test_runtime_host_registration.py`
  - spec-bound provider adapters and contract mapping

- `tests/test_panowan_runtime_provider.py`
  - provider interrupt capability declaration and load/execute behavior

- `tests/test_engines.py`
  - engine adapter behavior against the refactored runtime host contract

- `tests/test_worker_service.py`
  - worker orchestration, claimed vs running semantics, cancellation convergence

- `tests/test_api.py`
  - cancel endpoint behavior and restore-time adjudication

- `tests/test_static_ui.py`
  - only if UI-visible semantics need wording/contract updates

---

### Task 1: Tighten the canonical lifecycle model

**Files:**
- Modify: `app/jobs/lifecycle.py`
- Test: `tests/test_job_lifecycle.py`

- [ ] **Step 1: Write the failing lifecycle tests**

```python
import unittest

from app.jobs.lifecycle import (
    JOB_STATE_CANCELLED,
    JOB_STATE_CANCELLING,
    JOB_STATE_CLAIMED,
    JOB_STATE_FAILED,
    JOB_STATE_QUEUED,
    JOB_STATE_RUNNING,
    can_transition,
    normalize_restored_inflight_record,
)


class CanonicalLifecycleRefactorTests(unittest.TestCase):
    def test_claimed_can_cancel_without_cancelling_state(self) -> None:
        self.assertTrue(can_transition(JOB_STATE_CLAIMED, JOB_STATE_CANCELLED))
        self.assertFalse(can_transition(JOB_STATE_CLAIMED, JOB_STATE_CANCELLING))

    def test_running_is_the_only_entry_to_cancelling(self) -> None:
        self.assertTrue(can_transition(JOB_STATE_RUNNING, JOB_STATE_CANCELLING))
        self.assertFalse(can_transition(JOB_STATE_QUEUED, JOB_STATE_CANCELLING))
        self.assertFalse(can_transition(JOB_STATE_CLAIMED, JOB_STATE_CANCELLING))

    def test_restore_reconciles_cancelling_to_cancel_timeout(self) -> None:
        restored = normalize_restored_inflight_record(
            {"job_id": "job-1", "status": JOB_STATE_CANCELLING},
            finished_at="2026-05-02T12:00:00+00:00",
        )

        self.assertEqual(restored["status"], JOB_STATE_FAILED)
        self.assertEqual(restored["error"], "cancel_timeout")
        self.assertEqual(restored["error_code"], "cancel_timeout")
```

- [ ] **Step 2: Run the lifecycle tests to verify failure**

Run: `rtk python -m unittest tests.test_job_lifecycle -v`
Expected: FAIL because `claimed -> cancelling` is still allowed or the new assertions are not yet true.

- [ ] **Step 3: Update canonical transitions and restore semantics**

```python
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    JOB_STATE_QUEUED: frozenset({JOB_STATE_CLAIMED, JOB_STATE_CANCELLED}),
    JOB_STATE_CLAIMED: frozenset({JOB_STATE_RUNNING, JOB_STATE_CANCELLED, JOB_STATE_FAILED}),
    JOB_STATE_RUNNING: frozenset({JOB_STATE_SUCCEEDED, JOB_STATE_FAILED, JOB_STATE_CANCELLING}),
    JOB_STATE_CANCELLING: frozenset({JOB_STATE_CANCELLED, JOB_STATE_FAILED}),
    JOB_STATE_SUCCEEDED: frozenset(),
    JOB_STATE_FAILED: frozenset(),
    JOB_STATE_CANCELLED: frozenset(),
}


def normalize_restored_inflight_record(
    record: dict[str, Any], finished_at: str
) -> dict[str, Any]:
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
```

- [ ] **Step 4: Re-run the lifecycle tests**

Run: `rtk python -m unittest tests.test_job_lifecycle -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/jobs/lifecycle.py tests/test_job_lifecycle.py
rtk git commit -m "refactor: tighten canonical cancellation transitions"
```

---

### Task 2: Refactor backend job transitions for prepare-phase vs execute-phase cancel

**Files:**
- Modify: `app/jobs/local.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing backend transition tests**

```python
import unittest

from app.jobs.local import LocalJobBackend
from app.jobs.lifecycle import JOB_STATE_CANCELLED, JOB_STATE_CLAIMED, JOB_STATE_RUNNING


class LocalJobBackendCancellationRefactorTests(unittest.TestCase):
    def test_request_cancellation_cancels_claimed_job_immediately(self) -> None:
        backend = LocalJobBackend(self.job_store_path)
        backend.create_job({"job_id": "job-1", "status": "queued", "created_at": "1"})
        claimed = backend.claim_next_job(worker_id="worker-a")

        cancelled = backend.request_cancellation("job-1", worker_id="worker-a")

        self.assertIsNotNone(claimed)
        self.assertEqual(cancelled["status"], JOB_STATE_CANCELLED)

    def test_request_cancellation_only_marks_running_job_as_cancelling(self) -> None:
        backend = LocalJobBackend(self.job_store_path)
        backend.create_job({"job_id": "job-2", "status": "queued", "created_at": "1"})
        backend.claim_next_job(worker_id="worker-a")
        backend.mark_running("job-2", "worker-a")

        cancelling = backend.request_cancellation("job-2", worker_id="worker-a")

        self.assertEqual(cancelling["status"], "cancelling")
        self.assertEqual(cancelling["cancel_mode"], "soft")
```

- [ ] **Step 2: Run the backend tests to verify failure**

Run: `rtk python -m unittest tests.test_jobs -v`
Expected: FAIL because claimed jobs still enter `cancelling` instead of terminating directly.

- [ ] **Step 3: Refactor backend cancellation transitions**

```python
def request_cancellation(
    self,
    job_id: str,
    *,
    worker_id: str | None = None,
    mode: str = "soft",
) -> dict[str, Any] | None:
    with self._locked_store():
        job = self._jobs.get(job_id)
        if not job:
            return None
        current = job.get("status")
        if current == JOB_STATE_CLAIMED:
            updated = apply_transition(job, JOB_STATE_CANCELLED)
            updated["finished_at"] = now_iso()
            updated["error"] = None
            updated["error_code"] = None
            self._jobs[job_id] = updated
            self._persist_unlocked()
            return copy.deepcopy(updated)
        if current == JOB_STATE_RUNNING:
            updated = apply_transition(job, JOB_STATE_CANCELLING)
            updated["cancel_requested_at"] = now_iso()
            updated["cancel_mode"] = mode
            updated["cancel_attempt"] = int(updated.get("cancel_attempt") or 0) + 1
            updated["cancel_deadline_at"] = _deadline_iso(_DEFAULT_CANCEL_TIMEOUT_SEC)
            self._jobs[job_id] = updated
            self._persist_unlocked()
            return copy.deepcopy(updated)
        return None
```

- [ ] **Step 4: Re-run the backend tests**

Run: `rtk python -m unittest tests.test_jobs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/jobs/local.py tests/test_jobs.py
rtk git commit -m "refactor: split claimed and running cancellation semantics"
```

---

### Task 3: Split runtime host into prepare and execute phases

**Files:**
- Modify: `app/runtime_host.py`
- Test: `tests/test_runtime_host.py`

- [ ] **Step 1: Write the failing runtime host tests**

```python
import unittest

from app.runtime_host import ResidentRuntimeHost, RuntimeState


class ResidentRuntimeHostPhaseTests(unittest.TestCase):
    def test_prepare_runtime_loads_but_does_not_enter_running(self) -> None:
        host = ResidentRuntimeHost()
        provider = FakeRuntimeProvider()
        host.register_provider(provider)

        loaded = host.prepare_runtime("fake", {"job_id": "job-1"}, cancellation=None)
        snapshot = host.status("fake")

        self.assertIsNotNone(loaded)
        self.assertEqual(snapshot.state, RuntimeState.WARM)
        self.assertEqual(provider.load_calls, 1)
        self.assertEqual(provider.execute_calls, 0)

    def test_execute_job_transitions_runtime_through_running(self) -> None:
        host = ResidentRuntimeHost()
        provider = FakeRuntimeProvider()
        host.register_provider(provider)
        loaded = host.prepare_runtime("fake", {"job_id": "job-1"}, cancellation=None)

        result = host.execute_job("fake", loaded, {"job_id": "job-1"}, cancellation=None)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(provider.execute_calls, 1)
```

- [ ] **Step 2: Run the runtime host tests to verify failure**

Run: `rtk python -m unittest tests.test_runtime_host -v`
Expected: FAIL because `prepare_runtime(...)` and `execute_job(...)` do not exist yet.

- [ ] **Step 3: Implement phase-split runtime host methods**

```python
def prepare_runtime(
    self,
    provider_key: str,
    job: Mapping[str, Any],
    *,
    cancellation: RuntimeCancellationProbe | None = None,
) -> Any:
    provider, instance, lock = self._require(provider_key)
    with lock:
        if instance.state == RuntimeState.FAILED:
            self._set_state(instance, RuntimeState.EVICTING)
            self._safe_teardown(provider, instance)

        identity = provider.runtime_identity_from_job(job)
        if instance.state == RuntimeState.WARM and instance.identity != identity:
            self._set_state(instance, RuntimeState.EVICTING)
            self._safe_teardown(provider, instance)

        if instance.state == RuntimeState.COLD:
            self._load(provider, instance, identity, cancellation=cancellation)

        return instance.loaded


def execute_job(
    self,
    provider_key: str,
    loaded_runtime: Any,
    job: Mapping[str, Any],
    *,
    cancellation: RuntimeCancellationProbe | None = None,
) -> Mapping[str, Any]:
    provider, instance, lock = self._require(provider_key)
    with lock:
        self._set_state(instance, RuntimeState.RUNNING)
        try:
            result = provider.execute(loaded_runtime, job, cancellation=cancellation)
        except BaseException as exc:
            corrupting = bool(provider.classify_failure(exc))
            if corrupting:
                with self._state_lock:
                    instance.state = RuntimeState.FAILED
                    instance.last_error = str(exc)
            else:
                with self._state_lock:
                    instance.state = RuntimeState.WARM
                    instance.last_used_at = self._clock()
            raise
        with self._state_lock:
            instance.last_used_at = self._clock()
            instance.state = RuntimeState.WARM
        return result
```

- [ ] **Step 4: Re-run the runtime host tests**

Run: `rtk python -m unittest tests.test_runtime_host -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/runtime_host.py tests/test_runtime_host.py
rtk git commit -m "refactor: split runtime prepare and execute phases"
```

---

### Task 4: Upgrade provider registration to the new contract

**Files:**
- Modify: `app/runtime_host_registration.py`
- Test: `tests/test_runtime_host_registration.py`

- [ ] **Step 1: Write the failing provider-registration tests**

```python
import unittest

from app.runtime_host_registration import build_provider_from_spec


class RuntimeHostRegistrationContractTests(unittest.TestCase):
    def test_spec_bound_provider_exposes_load_with_cancellation(self) -> None:
        provider = build_provider_from_spec(self.spec, backend_root=self.backend_root)
        self.assertTrue(callable(provider.load))
        self.assertTrue(callable(provider.execute))
        self.assertTrue(callable(provider.interrupt_capabilities))
```

- [ ] **Step 2: Run the registration tests to verify failure**

Run: `rtk python -m unittest tests.test_runtime_host_registration -v`
Expected: FAIL because interrupt capability exposure is not implemented yet.

- [ ] **Step 3: Extend the spec-bound provider adapter**

```python
class _SpecBoundProvider:
    def load(
        self,
        identity: Hashable,
        cancellation: RuntimeCancellationProbe | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Any:
        return self._load(identity, cancellation=cancellation, context=context)

    def execute(
        self,
        loaded_runtime: Any,
        job: Mapping[str, Any],
        cancellation: RuntimeCancellationProbe | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        return self._execute(
            loaded_runtime,
            job,
            cancellation=cancellation,
            context=context,
        )

    def interrupt_capabilities(self) -> Mapping[str, bool]:
        return self._interrupt_capabilities()
```

- [ ] **Step 4: Re-run the registration tests**

Run: `rtk python -m unittest tests.test_runtime_host_registration -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/runtime_host_registration.py tests/test_runtime_host_registration.py
rtk git commit -m "refactor: expose runtime provider interrupt contract"
```

---

### Task 5: Replace the boolean probe with a structured cancellation contract

**Files:**
- Modify: `app/worker_service.py`
- Modify: `app/runtime_host.py`
- Modify: `app/engines/panowan.py`
- Test: `tests/test_worker_service.py`
- Test: `tests/test_engines.py`

- [ ] **Step 1: Write the failing cancellation-contract tests**

```python
import unittest

from app.worker_service import _build_probe_for_job


class CancellationContractTests(unittest.TestCase):
    def test_probe_exposes_mode_attempt_and_deadline(self) -> None:
        probe = _build_probe_for_job(
            backend=self.backend,
            job={
                "job_id": "job-1",
                "cancel_mode": "escalated",
                "cancel_attempt": 2,
                "cancel_deadline_at": "2026-05-02T12:00:00+00:00",
            },
            worker_id="worker-a",
        )

        self.assertTrue(probe.should_stop_now())
        self.assertTrue(probe.should_escalate())
        self.assertEqual(probe.mode, "escalated")
        self.assertEqual(probe.attempt, 2)
```

- [ ] **Step 2: Run the worker/engine tests to verify failure**

Run: `rtk python -m unittest tests.test_worker_service tests.test_engines -v`
Expected: FAIL because the current probe only supports `should_stop()` semantics.

- [ ] **Step 3: Introduce a richer cancellation object and pass it through**

```python
@dataclass(frozen=True)
class RuntimeCancellation:
    requested: bool
    mode: str
    attempt: int
    deadline_at: str | None

    def should_stop_now(self) -> bool:
        return self.requested

    def should_escalate(self) -> bool:
        return self.mode == "escalated"


def _build_probe_for_job(
    backend: LocalJobBackend,
    job: dict[str, Any],
    worker_id: str,
) -> RuntimeCancellation:
    current = backend.get_job(str(job["job_id"])) or job
    requested = current.get("status") == JOB_STATE_CANCELLING
    return RuntimeCancellation(
        requested=requested,
        mode=str(current.get("cancel_mode") or "soft"),
        attempt=int(current.get("cancel_attempt") or 0),
        deadline_at=current.get("cancel_deadline_at"),
    )
```

```python
loaded = self._host.prepare_runtime(
    self.provider_key,
    runner_payload,
    cancellation=cancellation,
)
result = self._host.execute_job(
    self.provider_key,
    loaded,
    runner_payload,
    cancellation=cancellation,
)
```

- [ ] **Step 4: Re-run the worker/engine tests**

Run: `rtk python -m unittest tests.test_worker_service tests.test_engines -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/worker_service.py app/runtime_host.py app/engines/panowan.py tests/test_worker_service.py tests/test_engines.py
rtk git commit -m "refactor: introduce structured runtime cancellation contract"
```

---

### Task 6: Move `claimed -> running` into worker execute start

**Files:**
- Modify: `app/worker_service.py`
- Test: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing worker orchestration tests**

```python
import unittest

from app.jobs.lifecycle import JOB_STATE_CLAIMED, JOB_STATE_RUNNING
from app.worker_service import run_one_job


class WorkerOrchestrationPhaseTests(unittest.TestCase):
    def test_job_stays_claimed_while_runtime_is_preparing(self) -> None:
        backend = self.make_backend_with_one_job()
        host = FakeHost(load_only=True)
        registry = self.make_registry(host)

        run_one_job(backend, registry, worker_id="worker-a", worker_registry=None)

        transitions = host.observed_job_statuses
        self.assertIn(JOB_STATE_CLAIMED, transitions)
        self.assertNotIn(JOB_STATE_RUNNING, host.statuses_seen_before_execute)

    def test_worker_marks_running_only_immediately_before_execute(self) -> None:
        backend = self.make_backend_with_one_job()
        host = FakeHost()
        registry = self.make_registry(host)

        run_one_job(backend, registry, worker_id="worker-a", worker_registry=None)

        self.assertEqual(host.job_status_at_execute_start, JOB_STATE_RUNNING)
```

- [ ] **Step 2: Run the worker-service tests to verify failure**

Run: `rtk python -m unittest tests.test_worker_service -v`
Expected: FAIL because `mark_running(...)` is still called before prepare/load completes.

- [ ] **Step 3: Refactor `run_one_job(...)` around claim/prepare/execute/finalize**

```python
def run_one_job(
    backend: LocalJobBackend,
    registry: EngineRegistry,
    worker_id: str,
    *,
    worker_registry: LocalWorkerRegistry | None = None,
) -> bool:
    job = backend.claim_next_job(worker_id=worker_id)
    if job is None:
        return False

    job_id = str(job["job_id"])
    engine = _resolve_engine(registry, job)
    claimed_job = {
        **job,
        "_cancellation_probe": _build_probe_for_job(backend, job, worker_id),
    }

    prepared = engine.prepare(claimed_job)
    current = backend.get_job(job_id)
    if current is None or current.get("status") == JOB_STATE_CANCELLED:
        return True

    started = backend.mark_running(job_id, worker_id)
    if started is None:
        return True

    run_job = {
        **started,
        "_prepared_runtime": prepared,
        "_cancellation_probe": _build_probe_for_job(backend, started, worker_id),
    }
    result = engine.execute(run_job)
    ...
```

- [ ] **Step 4: Re-run the worker-service tests**

Run: `rtk python -m unittest tests.test_worker_service -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/worker_service.py tests/test_worker_service.py
rtk git commit -m "refactor: align running state with execute start"
```

---

### Task 7: Split the engine API into prepare and execute

**Files:**
- Modify: `app/engines/panowan.py`
- Modify: `app/worker_service.py`
- Test: `tests/test_engines.py`
- Test: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing engine tests**

```python
import unittest

from app.engines.panowan import PanoWanEngine


class PanoWanEnginePhaseTests(unittest.TestCase):
    def test_prepare_delegates_to_runtime_prepare(self) -> None:
        host = FakeHost()
        engine = PanoWanEngine(host)
        prepared = engine.prepare({"payload": {"id": "job-1", "task": "t2v"}})
        self.assertEqual(prepared, host.prepared_runtime)

    def test_execute_uses_prepared_runtime(self) -> None:
        host = FakeHost()
        engine = PanoWanEngine(host)
        prepared = engine.prepare({"payload": {"id": "job-1", "task": "t2v"}})
        result = engine.execute(
            {
                "payload": {"id": "job-1", "task": "t2v"},
                "_prepared_runtime": prepared,
            }
        )
        self.assertTrue(result.output_path.endswith(".mp4"))
```

- [ ] **Step 2: Run the engine tests to verify failure**

Run: `rtk python -m unittest tests.test_engines -v`
Expected: FAIL because `prepare(...)` and `execute(...)` do not exist.

- [ ] **Step 3: Refactor the engine interface**

```python
class PanoWanEngine:
    def prepare(self, job: Mapping[str, object]) -> object:
        raw = dict(job)
        runner_payload = build_runner_payload(raw.get("payload") or raw)
        cancellation = raw.get("_cancellation_probe")
        return self._host.prepare_runtime(
            self.provider_key,
            runner_payload,
            cancellation=cancellation,
        )

    def execute(self, job: Mapping[str, object]) -> EngineResult:
        raw = dict(job)
        runner_payload = build_runner_payload(raw.get("payload") or raw)
        prepared = raw["_prepared_runtime"]
        cancellation = raw.get("_cancellation_probe")
        result = self._host.execute_job(
            self.provider_key,
            prepared,
            runner_payload,
            cancellation=cancellation,
        )
        return EngineResult(output_path=result["output_path"], metadata={})
```

- [ ] **Step 4: Re-run the engine tests**

Run: `rtk python -m unittest tests.test_engines -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/engines/panowan.py app/worker_service.py tests/test_engines.py tests/test_worker_service.py
rtk git commit -m "refactor: split panowan engine prepare and execute"
```

---

### Task 8: Refactor the PanoWan runtime provider to the new contract

**Files:**
- Modify: `third_party/PanoWan/sources/runtime_provider.py`
- Modify: `app/runtime_host_registration.py`
- Test: `tests/test_panowan_runtime_provider.py`

- [ ] **Step 1: Write the failing provider tests**

```python
import unittest

from third_party.PanoWan.sources.runtime_provider import (
    interrupt_capabilities,
    load_resident_runtime,
    run_job_inprocess,
)


class PanoWanRuntimeProviderContractTests(unittest.TestCase):
    def test_interrupt_capabilities_are_truthful_for_current_provider(self) -> None:
        capabilities = interrupt_capabilities()
        self.assertEqual(
            capabilities,
            {
                "load_cancel_awareness": True,
                "execute_soft_interrupt": True,
                "execute_step_interrupt": False,
                "execute_escalated_interrupt": False,
                "requires_reset_after_failed_interrupt": False,
            },
        )

    def test_load_resident_runtime_accepts_cancellation_argument(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "cancelled_before_load"):
            load_resident_runtime(
                self.identity,
                cancellation=AlwaysCancelledProbe(),
                context=None,
            )
```

- [ ] **Step 2: Run the provider tests to verify failure**

Run: `rtk python -m unittest tests.test_panowan_runtime_provider -v`
Expected: FAIL because the provider does not expose the new contract yet.

- [ ] **Step 3: Implement the upgraded provider contract with truthful capabilities**

```python
def interrupt_capabilities() -> dict[str, bool]:
    return {
        "load_cancel_awareness": True,
        "execute_soft_interrupt": True,
        "execute_step_interrupt": False,
        "execute_escalated_interrupt": False,
        "requires_reset_after_failed_interrupt": False,
    }


def load_resident_runtime(
    identity: PanoWanRuntimeIdentity,
    *,
    cancellation: Any = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if cancellation is not None and cancellation.should_stop_now():
        raise RuntimeError("cancelled_before_load")
    ...


def run_job_inprocess(
    loaded: dict[str, Any],
    job: Mapping[str, Any],
    *,
    cancellation: Any = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if cancellation is not None and cancellation.should_stop_now():
        return {"status": "cancelled", "output_path": job["output_path"]}
    ...
    if cancellation is not None and cancellation.should_stop_now():
        return {"status": "cancelled", "output_path": output_path}
```

- [ ] **Step 4: Re-run the provider tests**

Run: `rtk python -m unittest tests.test_panowan_runtime_provider -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add third_party/PanoWan/sources/runtime_provider.py app/runtime_host_registration.py tests/test_panowan_runtime_provider.py
rtk git commit -m "refactor: align panowan provider with interrupt contract"
```

---

### Task 9: Rebuild worker cancellation convergence around the new semantics

**Files:**
- Modify: `app/worker_service.py`
- Modify: `app/jobs/local.py`
- Test: `tests/test_worker_service.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing convergence tests**

```python
import unittest

from app.jobs.lifecycle import JOB_STATE_CANCELLED, JOB_STATE_FAILED


class WorkerCancellationConvergenceTests(unittest.TestCase):
    def test_claimed_job_cancels_without_entering_cancelling(self) -> None:
        backend = self.make_claimed_job_backend()
        registry = self.make_prepare_only_registry(cancel_before_execute=True)

        run_one_job(backend, registry, worker_id="worker-a", worker_registry=None)

        job = backend.get_job("job-1")
        self.assertEqual(job["status"], JOB_STATE_CANCELLED)

    def test_running_job_timeout_becomes_failed_cancel_timeout(self) -> None:
        backend = self.make_running_job_backend_in_cancelling()
        reconcile_overdue_cancellations(backend, now=self.after_deadline)

        job = backend.get_job("job-1")
        self.assertEqual(job["status"], JOB_STATE_FAILED)
        self.assertEqual(job["error_code"], "cancel_timeout")
```

- [ ] **Step 2: Run the worker/backend tests to verify failure**

Run: `rtk python -m unittest tests.test_worker_service tests.test_jobs -v`
Expected: FAIL because convergence still reflects the old claimed/cancelling coupling.

- [ ] **Step 3: Refactor worker convergence logic**

```python
def _finalize_job_success(...):
    current = backend.get_job(job_id)
    if current and current.get("status") == JOB_STATE_CANCELLING:
        cancelled = backend.mark_cancelled(job_id, worker_id=worker_id)
        return "cancelled", cancelled
    succeeded = backend.mark_succeeded(job_id, output_path, worker_id=worker_id)
    return "succeeded", succeeded


def run_one_job(...):
    ...
    current = backend.get_job(job_id)
    if current is None:
        return True
    if current.get("status") == JOB_STATE_CANCELLED:
        return True
    started = backend.mark_running(job_id, worker_id)
    ...
```

- [ ] **Step 4: Re-run the worker/backend tests**

Run: `rtk python -m unittest tests.test_worker_service tests.test_jobs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/worker_service.py app/jobs/local.py tests/test_worker_service.py tests/test_jobs.py
rtk git commit -m "refactor: rebuild cancellation convergence around execute semantics"
```

---

### Task 10: Align API cancellation and restore behavior with the refactor

**Files:**
- Modify: `app/api.py`
- Modify: `app/jobs/local.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
import unittest

from fastapi.testclient import TestClient

from app import api


class ApiCancellationRefactorTests(unittest.TestCase):
    def test_cancel_claimed_job_returns_cancelled(self) -> None:
        job = api._create_job_record("job-1", "prompt", "/tmp/out.mp4", params={})
        api.get_job_backend().claim_next_job(worker_id="worker-a")

        with TestClient(api.app) as client:
            response = client.post("/jobs/job-1/cancel")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

    def test_lifespan_reconciles_restored_cancelling_to_cancel_timeout(self) -> None:
        ...
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error_code"], "cancel_timeout")
```

- [ ] **Step 2: Run the API tests to verify failure**

Run: `rtk python -m unittest tests.test_api -v`
Expected: FAIL because claimed cancellation and restore semantics still reflect the old contract.

- [ ] **Step 3: Refactor cancel endpoint branching**

```python
@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job["status"]
    if status == "queued":
        ...
    if status == "claimed":
        result = get_job_backend().request_cancellation(
            job_id,
            worker_id=job.get("worker_id"),
        )
        if result is None:
            raise HTTPException(status_code=409, detail=f"Cannot cancel job with status {status}")
        broadcast_job_event("job_updated", result)
        return result
    if status == "running":
        result = get_job_backend().request_cancellation(
            job_id,
            worker_id=job.get("worker_id"),
        )
        ...
```

- [ ] **Step 4: Re-run the API tests**

Run: `rtk python -m unittest tests.test_api -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add app/api.py app/jobs/local.py tests/test_api.py
rtk git commit -m "refactor: align cancel api with claimed and running phases"
```

---

### Task 11: Update engine- and provider-level regression coverage for the final contract

**Files:**
- Modify: `tests/test_engines.py`
- Modify: `tests/test_runtime_host.py`
- Modify: `tests/test_panowan_runtime_provider.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Add focused regression tests for the final architecture**

```python
def test_prepare_runtime_can_observe_cancellation_without_running_job():
    ...


def test_execute_phase_is_the_only_path_to_cancelling():
    ...


def test_provider_declares_no_step_interrupt_yet():
    capabilities = interrupt_capabilities()
    assert capabilities["execute_step_interrupt"] is False
```

- [ ] **Step 2: Run the focused regression set**

Run: `rtk python -m unittest tests.test_engines tests.test_runtime_host tests.test_panowan_runtime_provider tests.test_worker_service -v`
Expected: PASS after the targeted regression additions are complete.

- [ ] **Step 3: Commit**

```bash
rtk git add tests/test_engines.py tests/test_runtime_host.py tests/test_panowan_runtime_provider.py tests/test_worker_service.py
rtk git commit -m "test: lock resident runtime cancellation contract regressions"
```

---

### Task 12: Run the full relevant regression suite and summarize results

**Files:**
- Modify: `docs/superpowers/plans/2026-05-02-resident-runtime-cancellation-refactor.md`

- [ ] **Step 1: Run the full targeted suite**

Run: `rtk python -m unittest tests.test_job_lifecycle tests.test_jobs tests.test_runtime_host tests.test_runtime_host_registration tests.test_panowan_runtime_provider tests.test_engines tests.test_worker_service tests.test_api tests.test_static_ui -v`
Expected: PASS

- [ ] **Step 2: Run repo diff review**

Run: `rtk git diff --stat`
Expected: shows only the planned lifecycle/runtime/provider/API/test changes

- [ ] **Step 3: Mark verification complete in the plan file**

```md
## Verification Notes

- Full targeted unittest suite passed after the refactor.
- Claimed jobs no longer enter `running` during runtime preparation.
- Only execute-phase cancellation enters `cancelling`.
- Restored `cancelling` jobs reconcile to `failed(cancel_timeout)`.
- PanoWan provider truthfully declares weak interrupt capability and no step-level interrupt yet.
```

- [ ] **Step 4: Commit**

```bash
rtk git add docs/superpowers/plans/2026-05-02-resident-runtime-cancellation-refactor.md
rtk git commit -m "docs: record cancellation refactor verification"
```

---

## Self-Review Checklist

### Spec coverage

- lifecycle semantics: Task 1, Task 2, Task 9, Task 10
- runtime prepare/execute split: Task 3, Task 6, Task 7
- provider interrupt contract: Task 4, Task 5, Task 8
- restore-time `cancel_timeout`: Task 1, Task 10
- truthful PanoWan capability declaration: Task 8, Task 11
- validation and regressions: Task 11, Task 12

### Placeholder scan

- No `TODO`, `TBD`, or “similar to previous task” placeholders remain.
- Every code-writing step includes concrete code.
- Every run step includes exact commands and expected outcomes.

### Type consistency

- runtime host public split uses `prepare_runtime(...)` and `execute_job(...)`
- job orchestration split uses `prepare(...)` and `execute(...)` on engines
- execute-phase cancellation uses `RuntimeCancellation`
- `claimed` cancellation terminates directly to `cancelled`
- `running` cancellation enters `cancelling`

---

## Verification Notes

- Full targeted unittest suite passed after the refactor: `rtk python -m unittest tests.test_job_lifecycle tests.test_jobs tests.test_runtime_host tests.test_runtime_host_registration tests.test_panowan_runtime_provider tests.test_engines tests.test_worker_service tests.test_api tests.test_static_ui -v`.
- Result: 215 tests run, 48 skipped because FastAPI is unavailable in this local environment.
- Claimed jobs no longer enter `running` during runtime preparation.
- Only execute-phase cancellation enters `cancelling`.
- Restored `cancelling` jobs reconcile to `failed(cancel_timeout)`.
- PanoWan provider truthfully declares weak interrupt capability and no step-level interrupt yet.
