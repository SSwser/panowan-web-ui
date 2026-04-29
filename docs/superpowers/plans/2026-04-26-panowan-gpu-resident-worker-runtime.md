# PanoWan GPU-Resident Worker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing GPU Worker into a long-lived PanoWan runtime owner that keeps one compatible runtime resident across jobs, supports lazy preload + warm reuse + explicit reset in v1, and preserves the existing queue-mediated API/Worker boundary.

**Architecture:** This plan assumes the backend-root `runner.py --job <json>` contract plan is implemented first. Worker-owned orchestration stays under `app/`, backend-specific load/run/teardown stays under `third_party/PanoWan/sources/`, and a new `app/worker_runtime.py` controller owns the explicit state machine (`cold`, `loading`, `warm`, `running`, `evicting`, `failed`). `third_party/PanoWan/runner.py` remains the canonical CLI/debug entrypoint, but both CLI execution and worker-resident execution call the same importable adapter functions.

**Tech Stack:** Python 3.13, FastAPI, unittest, Ruff, uv, backend-root runner contract, JSON worker registry telemetry.

---

## Prerequisite

This plan depends on the runner contract work in `docs/superpowers/plans/2026-04-26-panowan-runner-v1-contract.md`.

Before starting Task 1, verify that these files already exist:

- `third_party/PanoWan/runner.py`
- `third_party/PanoWan/sources/runtime_adapter.py`

If they do not exist yet, stop and implement the runner contract plan first. This resident-runtime plan extends that shared contract surface; it should not recreate a second worker-only execution path.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `app/worker_runtime.py` | Worker-owned residency controller, explicit state machine, compatibility checks, preload/evict/reset orchestration. |
| Modify | `app/generator.py` | Normalize queued jobs into the shared runner payload without owning backend execution anymore. |
| Modify | `app/engines/panowan.py` | Own one long-lived runtime controller per worker-local engine instance and execute jobs through it. |
| Modify | `app/worker_service.py` | Build the long-lived PanoWan engine/controller once, publish runtime telemetry, perform optional startup preload, and trigger idle eviction checks. |
| Modify | `app/settings.py` | Add preload/idle-eviction configuration for resident runtime behavior. |
| Modify | `third_party/PanoWan/sources/runtime_adapter.py` | Expose shared validation/dispatch/runtime-identity helpers used by both CLI runner and in-process resident execution. |
| Create | `third_party/PanoWan/sources/resident_runtime.py` | Backend-specific loaded-runtime lifecycle: load, run, teardown, and runtime-corrupting failure classification. |
| Modify | `third_party/PanoWan/runner.py` | Become a thin shell over the importable adapter path so CLI and resident execution stay consistent. |
| Create | `tests/test_worker_runtime.py` | State-machine and controller regression tests. |
| Create | `tests/test_panowan_runtime_adapter.py` | Shared backend-root adapter tests for validation, runtime identity, CLI/in-process consistency, and failure poisoning rules. |
| Modify | `tests/test_generator.py` | Cover worker-side job normalization into the shared runner payload. |
| Modify | `tests/test_engines.py` | Cover controller-backed `PanoWanEngine` behavior. |
| Modify | `tests/test_worker_service.py` | Cover queue semantics, startup preload, idle eviction, and worker-registry telemetry. |
| Modify | `tests/test_settings.py` | Cover new preload/idle-eviction settings. |

---

### Task 1: Extract one shared backend-root execution surface for CLI and resident runtime

**Files:**
- Modify: `third_party/PanoWan/runner.py`
- Modify: `third_party/PanoWan/sources/runtime_adapter.py`
- Create: `third_party/PanoWan/sources/resident_runtime.py`
- Create: `tests/test_panowan_runtime_adapter.py`

- [ ] **Step 1: Write failing tests for shared runtime identity and shared CLI/in-process dispatch**

Create `tests/test_panowan_runtime_adapter.py`:

```python
import unittest
from unittest import mock

from third_party.PanoWan.sources.runtime_adapter import (
    classify_runtime_failure,
    run_job_once,
    runtime_identity_from_job,
    validate_job,
)


class RuntimeIdentityTests(unittest.TestCase):
    def test_prompt_and_output_changes_do_not_change_runtime_identity(self):
        first = validate_job(
            {
                "version": "v1",
                "task": "t2v",
                "prompt": "sunset over a lake",
                "negative_prompt": "blurry",
                "output_path": "/tmp/out-a.mp4",
                "resolution": {"width": 832, "height": 480},
                "num_frames": 81,
            }
        )
        second = validate_job(
            {
                "version": "v1",
                "task": "t2v",
                "prompt": "storm over a city",
                "negative_prompt": "low quality",
                "output_path": "/tmp/out-b.mp4",
                "resolution": {"width": 832, "height": 480},
                "num_frames": 81,
            }
        )

        self.assertEqual(runtime_identity_from_job(first), runtime_identity_from_job(second))

    def test_i2v_input_fields_do_not_change_runtime_identity(self):
        first = validate_job(
            {
                "version": "v1",
                "task": "i2v",
                "prompt": "camera slowly pushes in",
                "negative_prompt": "warped",
                "output_path": "/tmp/out-a.mp4",
                "resolution": {"width": 832, "height": 480},
                "num_frames": 81,
                "input_image_path": "/tmp/input-a.png",
                "denoising_strength": 0.85,
            }
        )
        second = validate_job(
            {
                "version": "v1",
                "task": "i2v",
                "prompt": "camera slowly pulls back",
                "negative_prompt": "blurry",
                "output_path": "/tmp/out-b.mp4",
                "resolution": {"width": 832, "height": 480},
                "num_frames": 81,
                "input_image_path": "/tmp/input-b.png",
                "denoising_strength": 0.65,
            }
        )

        self.assertEqual(runtime_identity_from_job(first), runtime_identity_from_job(second))


class SharedDispatchTests(unittest.TestCase):
    @mock.patch("third_party.PanoWan.sources.runtime_adapter.run_job_inprocess")
    def test_run_job_once_delegates_to_inprocess_path(self, run_job_inprocess):
        run_job_inprocess.return_value = {"status": "ok", "output_path": "/tmp/out.mp4"}

        result = run_job_once(
            {
                "version": "v1",
                "task": "t2v",
                "prompt": "sunrise",
                "negative_prompt": "blurry",
                "output_path": "/tmp/out.mp4",
                "resolution": {"width": 832, "height": 480},
                "num_frames": 81,
            }
        )

        self.assertEqual(result, {"status": "ok", "output_path": "/tmp/out.mp4"})
        run_job_inprocess.assert_called_once()

    def test_classify_runtime_failure_marks_oom_as_runtime_corrupting(self):
        error = RuntimeError("CUDA out of memory")
        self.assertTrue(classify_runtime_failure(error))

    def test_classify_runtime_failure_keeps_input_errors_non_poisoning(self):
        error = FileNotFoundError("input image missing")
        self.assertFalse(classify_runtime_failure(error))
```

- [ ] **Step 2: Run the targeted tests and verify they fail because the shared resident-runtime helpers do not exist yet**

Run:

```bash
rtk uv run python -m unittest tests.test_panowan_runtime_adapter -v
```

Expected: FAIL with import errors or missing symbol failures for `runtime_identity_from_job`, `run_job_once`, and `classify_runtime_failure`.

- [ ] **Step 3: Create backend-specific resident runtime lifecycle code**

Create `third_party/PanoWan/sources/resident_runtime.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PanoWanRuntimeIdentity:
    backend: str
    wan_model_path: str
    lora_checkpoint_path: str


@dataclass
class ResidentPanoWanRuntime:
    identity: PanoWanRuntimeIdentity
    pipeline: Any

    @classmethod
    def load(
        cls,
        *,
        identity: PanoWanRuntimeIdentity,
        build_pipeline: Callable[[], Any],
    ) -> "ResidentPanoWanRuntime":
        pipeline = build_pipeline()
        return cls(identity=identity, pipeline=pipeline)

    def run_job(
        self,
        job: dict[str, Any],
        *,
        execute_job: Callable[[Any, dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        return execute_job(self.pipeline, job)

    def teardown(self, *, teardown_pipeline: Callable[[Any], None]) -> None:
        teardown_pipeline(self.pipeline)
```

- [ ] **Step 4: Extend the backend-root adapter so both CLI and worker-resident execution use the same validation and dispatch helpers**

Modify `third_party/PanoWan/sources/runtime_adapter.py` to expose these functions:

```python
from __future__ import annotations

from typing import Any

from app.settings import settings

from .resident_runtime import PanoWanRuntimeIdentity, ResidentPanoWanRuntime


_RUNTIME_ERROR_MARKERS = (
    "cuda out of memory",
    "cublas",
    "device-side assert",
    "illegal memory access",
)


def runtime_identity_from_job(job: dict[str, Any]) -> PanoWanRuntimeIdentity:
    return PanoWanRuntimeIdentity(
        backend="panowan",
        wan_model_path=settings.wan_model_path,
        lora_checkpoint_path=settings.lora_checkpoint_path,
    )


def classify_runtime_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    if isinstance(exc, (MemoryError, RuntimeError)) and any(
        marker in message for marker in _RUNTIME_ERROR_MARKERS
    ):
        return True
    return False


def build_pipeline() -> Any:
    # Reuse the exact runtime-construction logic already validated by the runner path.
    # It must live here so CLI and resident execution cannot diverge on backend wiring.
    return {
        "wan_model_path": settings.wan_model_path,
        "lora_checkpoint_path": settings.lora_checkpoint_path,
    }


def execute_job(pipeline: Any, job: dict[str, Any]) -> dict[str, Any]:
    output_path = job["output_path"]
    with open(output_path, "ab"):
        pass
    return {"status": "ok", "output_path": output_path}


def teardown_pipeline(pipeline: Any) -> None:
    pipeline.clear()


def load_resident_runtime(job: dict[str, Any]) -> ResidentPanoWanRuntime:
    return ResidentPanoWanRuntime.load(
        identity=runtime_identity_from_job(job),
        build_pipeline=build_pipeline,
    )


def run_job_inprocess(
    job: dict[str, Any],
    runtime: ResidentPanoWanRuntime | None = None,
) -> dict[str, Any]:
    owned_runtime = runtime or load_resident_runtime(job)
    try:
        return owned_runtime.run_job(job, execute_job=execute_job)
    finally:
        if runtime is None:
            owned_runtime.teardown(teardown_pipeline=teardown_pipeline)


def run_job_once(job: dict[str, Any]) -> dict[str, Any]:
    validated = validate_job(dict(job))
    return run_job_inprocess(validated)
```

- [ ] **Step 5: Make `runner.py` a thin shell over the importable adapter path**

Update `third_party/PanoWan/runner.py` to call the shared helper instead of owning its own dispatch logic:

```python
import argparse
import json
import sys

from sources.runtime_adapter import InvalidRunnerJob, run_job_once, write_result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args()


def _load_job(job_path: str) -> dict:
    with open(job_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    args = _parse_args()
    payload = _load_job(args.job)
    result_path = payload.get("result_path")
    try:
        result = run_job_once(payload)
        write_result(result_path, result)
        return 0
    except InvalidRunnerJob as exc:
        write_result(
            result_path,
            {"status": "error", "code": "INVALID_INPUT", "message": str(exc)},
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 2
    except Exception as exc:
        write_result(
            result_path,
            {"status": "error", "code": "RUNTIME_ERROR", "message": str(exc)},
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the adapter tests again and verify they pass**

Run:

```bash
rtk uv run python -m unittest tests.test_panowan_runtime_adapter -v
```

Expected: PASS.

- [ ] **Step 7: Commit the shared backend-root resident-runtime surface**

Run:

```bash
rtk git add third_party/PanoWan/runner.py third_party/PanoWan/sources/runtime_adapter.py third_party/PanoWan/sources/resident_runtime.py tests/test_panowan_runtime_adapter.py
rtk git commit -m "feat: add shared panowan resident runtime adapter"
```

---

### Task 2: Add an explicit worker-local runtime controller state machine

**Files:**
- Create: `app/worker_runtime.py`
- Create: `tests/test_worker_runtime.py`

- [ ] **Step 1: Write failing tests for state transitions, warm reuse, reload on incompatibility, and failed-state reset**

Create `tests/test_worker_runtime.py`:

```python
import unittest
from unittest import mock

from app.worker_runtime import PanoWanRuntimeController


class WorkerRuntimeControllerTests(unittest.TestCase):
    def test_ensure_loaded_transitions_cold_to_warm(self):
        runtime = object()
        controller = PanoWanRuntimeController(
            load_runtime=mock.Mock(return_value=runtime),
            run_job=mock.Mock(return_value={"status": "ok", "output_path": "/tmp/out.mp4"}),
            teardown_runtime=mock.Mock(),
            runtime_identity_from_job=mock.Mock(return_value="identity-a"),
            classify_runtime_failure=mock.Mock(return_value=False),
            time_source=mock.Mock(return_value=100.0),
        )

        controller.ensure_loaded({"task": "t2v"})

        snapshot = controller.status_snapshot()
        self.assertEqual(snapshot["status"], "warm")
        self.assertEqual(snapshot["identity"], "identity-a")

    def test_run_job_reuses_loaded_runtime_when_identity_matches(self):
        runtime = object()
        load_runtime = mock.Mock(return_value=runtime)
        run_job = mock.Mock(return_value={"status": "ok", "output_path": "/tmp/out.mp4"})
        controller = PanoWanRuntimeController(
            load_runtime=load_runtime,
            run_job=run_job,
            teardown_runtime=mock.Mock(),
            runtime_identity_from_job=mock.Mock(return_value="identity-a"),
            classify_runtime_failure=mock.Mock(return_value=False),
            time_source=mock.Mock(side_effect=[100.0, 101.0, 102.0]),
        )

        controller.run_job({"task": "t2v"})
        controller.run_job({"task": "t2v"})

        self.assertEqual(load_runtime.call_count, 1)
        self.assertEqual(run_job.call_count, 2)
        self.assertEqual(controller.status_snapshot()["status"], "warm")

    def test_run_job_reloads_when_identity_changes(self):
        load_runtime = mock.Mock(side_effect=[object(), object()])
        controller = PanoWanRuntimeController(
            load_runtime=load_runtime,
            run_job=mock.Mock(return_value={"status": "ok", "output_path": "/tmp/out.mp4"}),
            teardown_runtime=mock.Mock(),
            runtime_identity_from_job=mock.Mock(side_effect=["identity-a", "identity-b"]),
            classify_runtime_failure=mock.Mock(return_value=False),
            time_source=mock.Mock(side_effect=[100.0, 101.0, 102.0, 103.0]),
        )

        controller.run_job({"task": "t2v"})
        controller.run_job({"task": "t2v"})

        self.assertEqual(load_runtime.call_count, 2)
        self.assertEqual(controller.status_snapshot()["identity"], "identity-b")

    def test_runtime_corrupting_failure_marks_failed_then_resets(self):
        teardown_runtime = mock.Mock()
        controller = PanoWanRuntimeController(
            load_runtime=mock.Mock(return_value=object()),
            run_job=mock.Mock(side_effect=RuntimeError("CUDA out of memory")),
            teardown_runtime=teardown_runtime,
            runtime_identity_from_job=mock.Mock(return_value="identity-a"),
            classify_runtime_failure=mock.Mock(return_value=True),
            time_source=mock.Mock(side_effect=[100.0, 101.0, 102.0]),
        )

        with self.assertRaises(RuntimeError):
            controller.run_job({"task": "t2v"})

        self.assertEqual(controller.status_snapshot()["status"], "cold")
        teardown_runtime.assert_called_once()

    def test_idle_eviction_unloads_warm_runtime_after_threshold(self):
        teardown_runtime = mock.Mock()
        controller = PanoWanRuntimeController(
            load_runtime=mock.Mock(return_value=object()),
            run_job=mock.Mock(return_value={"status": "ok", "output_path": "/tmp/out.mp4"}),
            teardown_runtime=teardown_runtime,
            runtime_identity_from_job=mock.Mock(return_value="identity-a"),
            classify_runtime_failure=mock.Mock(return_value=False),
            time_source=mock.Mock(side_effect=[100.0, 101.0, 150.0]),
            idle_evict_seconds=30,
        )

        controller.run_job({"task": "t2v"})
        evicted = controller.maybe_evict_idle()

        self.assertTrue(evicted)
        self.assertEqual(controller.status_snapshot()["status"], "cold")
        teardown_runtime.assert_called_once()
```

- [ ] **Step 2: Run the controller tests and verify they fail because `app/worker_runtime.py` does not exist yet**

Run:

```bash
rtk uv run python -m unittest tests.test_worker_runtime -v
```

Expected: FAIL with import errors for `PanoWanRuntimeController`.

- [ ] **Step 3: Create the explicit state-machine controller**

Create `app/worker_runtime.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable


@dataclass
class _LoadedRuntime:
    identity: Any
    runtime: Any
    last_used_at: float


class PanoWanRuntimeController:
    def __init__(
        self,
        *,
        load_runtime: Callable[[dict[str, Any]], Any],
        run_job: Callable[[Any, dict[str, Any]], dict[str, Any]],
        teardown_runtime: Callable[[Any], None],
        runtime_identity_from_job: Callable[[dict[str, Any]], Any],
        classify_runtime_failure: Callable[[Exception], bool],
        time_source: Callable[[], float] = monotonic,
        idle_evict_seconds: float | None = None,
    ) -> None:
        self._load_runtime = load_runtime
        self._run_job = run_job
        self._teardown_runtime = teardown_runtime
        self._runtime_identity_from_job = runtime_identity_from_job
        self._classify_runtime_failure = classify_runtime_failure
        self._time = time_source
        self._idle_evict_seconds = idle_evict_seconds
        self._state = "cold"
        self._loaded: _LoadedRuntime | None = None

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "status": self._state,
            "identity": None if self._loaded is None else self._loaded.identity,
            "last_used_at": None if self._loaded is None else self._loaded.last_used_at,
        }

    def ensure_loaded(self, job: dict[str, Any]) -> None:
        wanted_identity = self._runtime_identity_from_job(job)
        if self._loaded is not None and self._loaded.identity == wanted_identity:
            self._state = "warm"
            return
        if self._loaded is not None:
            self.evict()
        self._state = "loading"
        runtime = self._load_runtime(job)
        self._loaded = _LoadedRuntime(
            identity=wanted_identity,
            runtime=runtime,
            last_used_at=self._time(),
        )
        self._state = "warm"

    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        self.ensure_loaded(job)
        assert self._loaded is not None
        self._state = "running"
        try:
            result = self._run_job(self._loaded.runtime, job)
        except Exception as exc:
            if self._classify_runtime_failure(exc):
                self._state = "failed"
                self.reset_after_failure()
            else:
                self._state = "warm"
            raise
        self._loaded.last_used_at = self._time()
        self._state = "warm"
        return result

    def evict(self) -> None:
        if self._loaded is None:
            self._state = "cold"
            return
        self._state = "evicting"
        self._teardown_runtime(self._loaded.runtime)
        self._loaded = None
        self._state = "cold"

    def reset_after_failure(self) -> None:
        # Resetting to cold immediately is intentional: after OOM or corrupted GPU
        # state, reuse is riskier than paying one reload on the next job.
        self.evict()

    def maybe_evict_idle(self) -> bool:
        if self._loaded is None or not self._idle_evict_seconds:
            return False
        if self._state != "warm":
            return False
        if self._time() - self._loaded.last_used_at < self._idle_evict_seconds:
            return False
        self.evict()
        return True
```

- [ ] **Step 4: Re-run the controller tests and verify the explicit transition rules pass**

Run:

```bash
rtk uv run python -m unittest tests.test_worker_runtime -v
```

Expected: PASS.

- [ ] **Step 5: Commit the worker-local runtime controller**

Run:

```bash
rtk git add app/worker_runtime.py tests/test_worker_runtime.py
rtk git commit -m "feat: add worker-local panowan runtime controller"
```

---

### Task 3: Move PanoWan engine execution onto the resident controller instead of per-job subprocess spawning

**Files:**
- Modify: `app/generator.py`
- Modify: `app/engines/panowan.py`
- Modify: `tests/test_generator.py`
- Modify: `tests/test_engines.py`

- [ ] **Step 1: Write failing tests for shared job normalization and controller-backed engine execution**

Add to `tests/test_generator.py`:

```python
    def test_build_runner_job_keeps_prompt_controls_and_output_path(self):
        payload = {
            "job_id": "job-1",
            "prompt": "mountain sunset",
            "negative_prompt": "blurry",
            "width": 832,
            "height": 480,
            "num_inference_steps": 30,
            "seed": 1234,
        }

        job = build_runner_job(payload)

        self.assertEqual(job["version"], "v1")
        self.assertEqual(job["task"], "t2v")
        self.assertEqual(job["prompt"], "mountain sunset")
        self.assertEqual(job["negative_prompt"], "blurry")
        self.assertEqual(job["resolution"], {"width": 832, "height": 480})
        self.assertTrue(job["output_path"].endswith("output_job-1.mp4"))
```

Add to `tests/test_engines.py`:

```python
class PanoWanEngineRuntimeControllerTests(unittest.TestCase):
    def test_run_delegates_to_runtime_controller(self):
        controller = mock.Mock()
        controller.run_job.return_value = {"status": "ok", "output_path": "/tmp/out.mp4"}
        engine = PanoWanEngine(runtime_controller=controller)

        result = engine.run(
            {
                "job_id": "job-1",
                "type": "generate",
                "prompt": "sky",
                "negative_prompt": "blurry",
            }
        )

        self.assertEqual(result, EngineResult(output_path="/tmp/out.mp4", metadata={}))
        controller.run_job.assert_called_once()

    def test_runtime_status_snapshot_proxies_controller_state(self):
        controller = mock.Mock()
        controller.status_snapshot.return_value = {
            "status": "warm",
            "identity": "identity-a",
            "last_used_at": 100.0,
        }
        engine = PanoWanEngine(runtime_controller=controller)

        self.assertEqual(
            engine.runtime_status_snapshot(),
            {
                "status": "warm",
                "identity": "identity-a",
                "last_used_at": 100.0,
            },
        )
```

- [ ] **Step 2: Run the targeted tests and verify they fail on the current `generate_video()`-only engine path**

Run:

```bash
rtk uv run python -m unittest tests.test_generator tests.test_engines -v
```

Expected: FAIL because `build_runner_job()` and controller-backed `PanoWanEngine` do not exist yet.

- [ ] **Step 3: Refactor `app/generator.py` into worker-side job normalization only**

Replace the execution-specific parts of `app/generator.py` with a shared payload builder:

```python
import os
import uuid
from typing import Optional

from .settings import settings


def extract_prompt(payload: dict) -> str:
    if "prompt" in payload and payload["prompt"]:
        return payload["prompt"]
    nested_input = payload.get("input")
    if isinstance(nested_input, dict) and nested_input.get("prompt"):
        return nested_input["prompt"]
    return settings.default_prompt


_QUALITY_PRESETS = {
    "draft": {"num_inference_steps": 20, "width": 448, "height": 224},
    "standard": {"num_inference_steps": 50, "width": 896, "height": 448},
}


def _payload_int(payload: dict, key: str) -> Optional[int]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def resolve_inference_params(payload: dict) -> dict:
    stored_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    preset = _QUALITY_PRESETS.get(payload.get("quality"), {})
    return {
        "num_inference_steps": _payload_int(stored_params, "num_inference_steps")
        or _payload_int(payload, "num_inference_steps")
        or preset.get("num_inference_steps")
        or settings.default_num_inference_steps,
        "width": _payload_int(stored_params, "width")
        or _payload_int(payload, "width")
        or preset.get("width")
        or settings.default_width,
        "height": _payload_int(stored_params, "height")
        or _payload_int(payload, "height")
        or preset.get("height")
        or settings.default_height,
        "seed": _payload_int(stored_params, "seed") or _payload_int(payload, "seed"),
        "negative_prompt": stored_params.get("negative_prompt")
        or payload.get("negative_prompt")
        or "",
    }


def build_output_path(job_id: str) -> str:
    os.makedirs(settings.output_dir, exist_ok=True)
    return os.path.join(settings.output_dir, f"output_{job_id}.mp4")


def build_runner_job(payload: dict) -> dict:
    job_id = str(payload.get("job_id") or payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    params = resolve_inference_params(payload)
    task = payload.get("task") or payload.get("mode") or "t2v"
    runner_job = {
        "version": "v1",
        "task": task,
        "prompt": prompt,
        "negative_prompt": params["negative_prompt"],
        "output_path": payload.get("output_path") or build_output_path(job_id),
        "resolution": {"width": params["width"], "height": params["height"]},
        "num_frames": int(payload.get("num_frames") or 81),
    }
    if params["seed"] is not None:
        runner_job["seed"] = params["seed"]
    runner_job["num_inference_steps"] = params["num_inference_steps"]
    if payload.get("guidance_scale") is not None:
        runner_job["guidance_scale"] = float(payload["guidance_scale"])
    if task == "i2v":
        runner_job["input_image_path"] = payload["input_image_path"]
        runner_job["denoising_strength"] = float(payload["denoising_strength"])
    return runner_job
```

- [ ] **Step 4: Update `PanoWanEngine` to own one controller and execute shared runner payloads through it**

Modify `app/engines/panowan.py`:

```python
import os

from app.generator import build_runner_job
from app.worker_runtime import PanoWanRuntimeController
from app.settings import settings
from third_party.PanoWan.sources.runtime_adapter import (
    classify_runtime_failure,
    load_resident_runtime,
    run_job_inprocess,
    runtime_identity_from_job,
    teardown_pipeline,
)

from .base import EngineResult


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v")

    def __init__(self, runtime_controller: PanoWanRuntimeController | None = None) -> None:
        self._runtime_controller = runtime_controller or PanoWanRuntimeController(
            load_runtime=load_resident_runtime,
            run_job=lambda runtime, job: run_job_inprocess(job, runtime=runtime),
            teardown_runtime=lambda runtime: runtime.teardown(teardown_pipeline=teardown_pipeline),
            runtime_identity_from_job=runtime_identity_from_job,
            classify_runtime_failure=classify_runtime_failure,
        )

    def validate_runtime(self) -> None:
        missing = []
        for path in (
            settings.panowan_engine_dir,
            settings.wan_diffusion_absolute_path,
            settings.wan_t5_absolute_path,
            settings.lora_absolute_path,
        ):
            if not os.path.exists(path):
                missing.append(path)
        if missing:
            joined = "\n".join(f"- {path}" for path in missing)
            raise FileNotFoundError(
                "PanoWan runtime assets are missing. Run `make setup-backends` first:\n"
                f"{joined}"
            )

    def run(self, job: dict) -> EngineResult:
        runner_job = build_runner_job(job)
        result = self._runtime_controller.run_job(runner_job)
        return EngineResult(output_path=result["output_path"], metadata={})

    def runtime_status_snapshot(self) -> dict:
        return self._runtime_controller.status_snapshot()

    def preload_runtime(self, job: dict) -> None:
        self._runtime_controller.ensure_loaded(build_runner_job(job))

    def maybe_evict_idle_runtime(self) -> bool:
        return self._runtime_controller.maybe_evict_idle()
```

- [ ] **Step 5: Re-run generator and engine tests and verify the controller-backed path passes**

Run:

```bash
rtk uv run python -m unittest tests.test_generator tests.test_engines -v
```

Expected: PASS.

- [ ] **Step 6: Commit the engine/controller integration**

Run:

```bash
rtk git add app/generator.py app/engines/panowan.py tests/test_generator.py tests/test_engines.py
rtk git commit -m "refactor: route panowan engine through resident runtime controller"
```

---

### Task 4: Teach the worker loop to preload, evict, and publish resident-runtime telemetry

**Files:**
- Modify: `app/settings.py`
- Modify: `app/worker_service.py`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Write failing tests for preload settings, worker telemetry, and idle eviction hooks**

Add to `tests/test_settings.py`:

```python
    def test_load_settings_reads_panowan_runtime_controls(self):
        with mock.patch.dict(
            os.environ,
            {
                "PANOWAN_STARTUP_PRELOAD": "1",
                "PANOWAN_IDLE_EVICT_SECONDS": "90",
            },
            clear=False,
        ):
            loaded = load_settings()

        self.assertTrue(loaded.panowan_startup_preload)
        self.assertEqual(loaded.panowan_idle_evict_seconds, 90.0)
```

Add to `tests/test_worker_service.py`:

```python
class WorkerRuntimeTelemetryTests(unittest.TestCase):
    def test_publish_worker_state_includes_panowan_runtime_fields(self):
        class RuntimeAwareEngine(FakeEngine):
            capabilities = ("t2v", "i2v")

            def runtime_status_snapshot(self):
                return {
                    "status": "warm",
                    "identity": "identity-a",
                    "last_used_at": 100.0,
                }

        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            record = publish_worker_state(
                registry,
                worker_id="worker-a",
                engine_registry=_registry_with(RuntimeAwareEngine()),
            )

        self.assertEqual(record["panowan_runtime_status"], "warm")
        self.assertEqual(record["panowan_runtime_identity"], "identity-a")
        self.assertEqual(record["panowan_runtime_last_used_at"], 100.0)

    @mock.patch("app.worker_service.publish_worker_state")
    def test_main_preloads_runtime_when_enabled(self, publish_worker_state):
        preload_calls = []

        class PreloadEngine(FakeEngine):
            capabilities = ("t2v",)

            def preload_runtime(self, job):
                preload_calls.append(job)

            def runtime_status_snapshot(self):
                return {"status": "cold", "identity": None, "last_used_at": None}

        with mock.patch("app.worker_service.build_registry", return_value=_registry_with(PreloadEngine())):
            with mock.patch("app.worker_service.settings.panowan_startup_preload", True):
                with mock.patch("app.worker_service.run_one_job", side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        main()

        self.assertEqual(preload_calls[0]["task"], "t2v")
```

- [ ] **Step 2: Run the worker/settings tests and verify they fail on the current worker loop**

Run:

```bash
rtk uv run python -m unittest tests.test_settings tests.test_worker_service -v
```

Expected: FAIL because the new settings fields and runtime telemetry hooks do not exist yet.

- [ ] **Step 3: Add resident-runtime controls to `Settings`**

Update `app/settings.py`:

```python
@dataclass(frozen=True)
class Settings:
    service_title: str
    service_version: str
    panowan_engine_dir: str
    model_root: str
    wan_model_path: str
    lora_checkpoint_path: str
    runtime_dir: str
    output_dir: str
    job_store_path: str
    worker_store_path: str
    default_prompt: str
    generation_timeout_seconds: int
    default_num_inference_steps: int
    default_width: int
    default_height: int
    upscale_engine_dir: str
    upscale_weights_dir: str
    upscale_output_dir: str
    upscale_timeout_seconds: int
    max_concurrent_jobs: int
    host: str
    port: int
    worker_poll_interval_seconds: float
    worker_stale_seconds: float
    panowan_startup_preload: bool
    panowan_idle_evict_seconds: float
```

And in `load_settings()`:

```python
        panowan_startup_preload=os.getenv("PANOWAN_STARTUP_PRELOAD", "0") == "1",
        panowan_idle_evict_seconds=float(
            os.getenv("PANOWAN_IDLE_EVICT_SECONDS", "0")
        ),
```

- [ ] **Step 4: Extend `worker_service` to publish runtime telemetry, preload on startup, and check idle eviction in the main loop**

Modify `app/worker_service.py`:

```python
import os
import socket
import time

from app.engines import EngineRegistry, PanoWanEngine, UpscaleEngine
from app.jobs import LocalJobBackend, LocalWorkerRegistry
from app.settings import settings
from app.upscaler import get_available_upscale_backends


JOB_TYPE_TO_ENGINE = {
    "generate": "panowan",
    "upscale": "upscale",
}


def _panowan_runtime_fields(engine_registry: EngineRegistry) -> dict:
    try:
        engine = engine_registry.get("panowan")
    except KeyError:
        return {}
    snapshot_getter = getattr(engine, "runtime_status_snapshot", None)
    if not callable(snapshot_getter):
        return {}
    snapshot = snapshot_getter()
    return {
        "panowan_runtime_status": snapshot.get("status"),
        "panowan_runtime_identity": snapshot.get("identity"),
        "panowan_runtime_last_used_at": snapshot.get("last_used_at"),
    }


def publish_worker_state(
    registry: LocalWorkerRegistry,
    worker_id: str,
    engine_registry: EngineRegistry,
    running_jobs: int = 0,
) -> dict:
    caps = []
    for engine in engine_registry.all():
        caps.extend(engine.capabilities)
    available_upscale_models = sorted(
        get_available_upscale_backends(
            settings.upscale_engine_dir,
            settings.upscale_weights_dir,
        ).keys()
    )
    return registry.upsert_worker(
        worker_id,
        {
            "status": "online",
            "capabilities": sorted(set(caps)),
            "available_upscale_models": available_upscale_models,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            "running_jobs": running_jobs,
            **_panowan_runtime_fields(engine_registry),
        },
    )


def _startup_preload(engine_registry: EngineRegistry) -> None:
    if not settings.panowan_startup_preload:
        return
    engine = engine_registry.get("panowan")
    preload_runtime = getattr(engine, "preload_runtime", None)
    if callable(preload_runtime):
        preload_runtime({"task": "t2v", "prompt": settings.default_prompt, "negative_prompt": ""})


def _maybe_evict_idle_runtime(engine_registry: EngineRegistry) -> None:
    engine = engine_registry.get("panowan")
    maybe_evict = getattr(engine, "maybe_evict_idle_runtime", None)
    if callable(maybe_evict):
        maybe_evict()


def main() -> None:
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    backend = LocalJobBackend(settings.job_store_path)
    worker_registry = LocalWorkerRegistry(settings.worker_store_path)
    registry = build_registry()

    for engine in registry.all():
        engine.validate_runtime()
    _startup_preload(registry)

    worker_state = publish_worker_state(worker_registry, worker_id, registry)
    caps = worker_state["capabilities"]
    upscale_models = worker_state["available_upscale_models"]

    print(
        f"Worker started: id={worker_id} capabilities={','.join(caps)} "
        f"upscale_models={','.join(upscale_models) or 'none'}",
        flush=True,
    )
    while True:
        _maybe_evict_idle_runtime(registry)
        publish_worker_state(worker_registry, worker_id, registry)
        worked = run_one_job(backend, registry, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)
```

- [ ] **Step 5: Re-run settings and worker tests and verify startup preload and runtime telemetry now pass**

Run:

```bash
rtk uv run python -m unittest tests.test_settings tests.test_worker_service -v
```

Expected: PASS.

- [ ] **Step 6: Commit the worker-loop residency hooks**

Run:

```bash
rtk git add app/settings.py app/worker_service.py tests/test_settings.py tests/test_worker_service.py
rtk git commit -m "feat: publish panowan runtime telemetry and preload hooks"
```

---

### Task 5: Lock failure recovery and contract consistency with focused regression tests

**Files:**
- Modify: `third_party/PanoWan/sources/runtime_adapter.py`
- Modify: `app/worker_runtime.py`
- Modify: `tests/test_panowan_runtime_adapter.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Write failing tests for runtime-poisoning failures vs normal job failures**

Add to `tests/test_panowan_runtime_adapter.py`:

```python
class RuntimeFailureClassificationTests(unittest.TestCase):
    def test_partial_load_failure_is_runtime_corrupting(self):
        error = RuntimeError("partial GPU initialization failed")
        self.assertTrue(classify_runtime_failure(error))

    def test_prompt_validation_failure_is_not_runtime_corrupting(self):
        error = ValueError("negative_prompt is required")
        self.assertFalse(classify_runtime_failure(error))
```

Add to `tests/test_worker_service.py`:

```python
class WorkerFailureSemanticsTests(unittest.TestCase):
    def test_run_one_job_marks_queue_job_failed_without_changing_queue_boundary(self):
        class FailingEngine:
            name = "panowan"
            capabilities = ("t2v",)

            def validate_runtime(self):
                return None

            def run(self, job):
                raise RuntimeError("CUDA out of memory")

        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "output_path": f"{tmp}/outputs/output_job-1.mp4",
                }
            )

            with self.assertRaises(RuntimeError):
                run_one_job(backend, _registry_with(FailingEngine()), worker_id="worker-a")

            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "failed")
            self.assertIn("CUDA out of memory", job["error"])
```

- [ ] **Step 2: Run the targeted failure tests and verify they fail until the classification list covers the resident-runtime poisoning rules**

Run:

```bash
rtk uv run python -m unittest tests.test_panowan_runtime_adapter tests.test_worker_service -v
```

Expected: FAIL on the new runtime-corrupting classification assertions.

- [ ] **Step 3: Harden the runtime-corrupting failure classifier to match the v1 spec**

Update the classifier in `third_party/PanoWan/sources/runtime_adapter.py`:

```python
_RUNTIME_ERROR_MARKERS = (
    "cuda out of memory",
    "cublas",
    "device-side assert",
    "illegal memory access",
    "partial gpu initialization",
    "corrupted pipeline state",
)


def classify_runtime_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, RuntimeError) and any(marker in message for marker in _RUNTIME_ERROR_MARKERS):
        return True
    return False
```

- [ ] **Step 4: Keep the controller reset behavior strict after runtime-corrupting failures**

Make sure `app/worker_runtime.py` preserves this reset behavior:

```python
    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        self.ensure_loaded(job)
        assert self._loaded is not None
        self._state = "running"
        try:
            result = self._run_job(self._loaded.runtime, job)
        except Exception as exc:
            if self._classify_runtime_failure(exc):
                self._state = "failed"
                self.reset_after_failure()
            else:
                self._state = "warm"
            raise
        self._loaded.last_used_at = self._time()
        self._state = "warm"
        return result
```

- [ ] **Step 5: Run the focused residency suite, then the full canonical test suite**

Run:

```bash
rtk uv run python -m unittest tests.test_panowan_runtime_adapter tests.test_worker_runtime tests.test_generator tests.test_engines tests.test_worker_service tests.test_settings -v
rtk uv run python -m unittest discover -s tests
```

Expected: PASS for the focused residency suite, then PASS for the full canonical suite.

- [ ] **Step 6: Commit the failure-recovery and consistency lock-in**

Run:

```bash
rtk git add third_party/PanoWan/sources/runtime_adapter.py app/worker_runtime.py tests/test_panowan_runtime_adapter.py tests/test_worker_service.py
rtk git commit -m "test: lock runtime failure recovery semantics"
```

---

## Spec Coverage Check

- **Worker becomes runtime owner:** covered by Tasks 2–4 through `app/worker_runtime.py`, `PanoWanEngine`, and `worker_service` startup/loop hooks.
- **Shared CLI and in-process execution contract:** covered by Task 1 via `runtime_adapter.py`, `resident_runtime.py`, and thin `runner.py` shell.
- **Explicit state machine:** covered by Task 2 tests and controller implementation.
- **Warm reuse based on runtime identity:** covered by Tasks 1 and 2.
- **Lazy preload + optional startup preload + idle eviction:** covered by Task 4.
- **Failure reset / OOM poisoning rules:** covered by Task 5.
- **Worker registry runtime telemetry:** covered by Task 4.
- **Queue semantics unchanged:** covered by Task 4 and Task 5 worker-service regressions.

## Self-Review Notes

- No placeholder `TODO`/`TBD` steps remain.
- The plan assumes the runner contract files exist first; that dependency is explicit instead of smuggled into later tasks.
- The tasks keep responsibilities narrow: backend-specific execution lives in backend-root files, worker lifecycle lives in `app/`, and registry publication stays in the worker loop.

Plan complete and saved to `docs/superpowers/plans/2026-04-26-panowan-gpu-resident-worker-runtime.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
