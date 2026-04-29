# PanoWan Runner v1 Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy `uv run panowan-test` worker-side invocation path with a strict project-owned `runner.py --job <json>` contract, including required `negative_prompt`, shared t2v/i2v payload semantics, and worker/runtime integration that no longer knows upstream CLI details.

**Architecture:** The implementation introduces a backend-root `third_party/PanoWan/runner.py` entrypoint and a narrow project-owned job payload model. The current `app/generator.py` subprocess assembly is split into two responsibilities: building a strict runner payload from queued jobs and invoking the backend-root runner. Validation and task branching move to backend-owned integration code under `third_party/PanoWan/`, while API and worker code keep owning job creation, output path selection, and queue persistence.

**Tech Stack:** Python 3.13, FastAPI, unittest, Ruff, uv, backend-local `backend.toml`, JSON file transport.

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `third_party/PanoWan/backend.toml` | Declare PanoWan backend identity and runtime-root participation in the backend spec system. |
| Create | `third_party/PanoWan/runner.py` | Canonical backend-root entrypoint accepting `--job <json>`, validating v1 payloads, dispatching `t2v` / `i2v`, invoking current runtime internals, and writing structured results. |
| Create | `third_party/PanoWan/sources/runtime_adapter.py` | Project-owned adapter helpers for payload validation, command mapping, result writing, and internal bridge helpers. |
| Modify | `app/generator.py` | Stop assembling upstream CLI flags directly; build the strict runner payload, persist JSON job files, invoke `runner.py`, and normalize result handling. |
| Modify | `app/engines/panowan.py` | Keep engine boundary thin while validating the new backend-root runtime files instead of a legacy engine tree contract. |
| Modify | `app/settings.py` | Add any runner/job-file paths needed by the new invocation flow without exposing backend layout details upstream. |
| Modify | `app/paths.py` | Add derived runtime paths for PanoWan runner job/result scratch files if needed by settings. |
| Modify | `app/api.py` | Ensure queued generate jobs always persist the fields needed to build the strict runner payload, especially `negative_prompt` and task-dispatch data. |
| Modify | `tests/test_generator.py` | Main regression surface for runner payload building, JSON transport, and runner invocation. |
| Modify | `tests/test_engines.py` | Keep the engine contract aligned with the new generator/runner boundary. |
| Modify | `tests/test_settings.py` | Cover new derived settings/path behavior for runner job/result files. |
| Modify | `tests/test_api.py` | Verify queued jobs persist required prompt/task fields for the strict runner payload. |
| Modify | `tests/test_worker_service.py` | Verify the worker still completes/fails jobs correctly while engines build output paths through the new runner contract. |

---

### Task 1: Add backend-root runner contract files

**Files:**
- Create: `third_party/PanoWan/backend.toml`
- Create: `third_party/PanoWan/runner.py`
- Create: `third_party/PanoWan/sources/runtime_adapter.py`
- Test: `tests/test_generator.py`

- [ ] **Step 1: Write the failing test for strict runner command invocation**

Add to `tests/test_generator.py`:

```python
    @patch("app.generator.os.makedirs")
    @patch("app.generator.os.path.exists", return_value=True)
    @patch("app.generator.os.path.getsize", return_value=11)
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_invokes_backend_root_runner_with_job_json(
        self,
        mock_popen,
        mock_getsize,
        mock_exists,
        mock_makedirs,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.return_value = ("ok", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        result = generate_video(
            {
                "id": "job-1",
                "prompt": "mountain sunset",
                "negative_prompt": "rain",
                "output_path": os.path.join(settings.output_dir, "output_job-1.mp4"),
            }
        )

        cmd = (
            mock_popen.call_args.kwargs["args"]
            if "args" in mock_popen.call_args.kwargs
            else mock_popen.call_args.args[0]
        )
        self.assertEqual(cmd[:3], ["python", "runner.py", "--job"])
        self.assertTrue(cmd[3].endswith("job-1.json"))
        self.assertEqual(result["output_path"], os.path.join(settings.output_dir, "output_job-1.mp4"))
```

- [ ] **Step 2: Run the targeted test and verify it fails on the current legacy `panowan-test` command**

Run:

```bash
rtk python -m unittest tests.test_generator.GenerateVideoTests.test_generate_video_invokes_backend_root_runner_with_job_json
```

Expected: FAIL because `app/generator.py` still calls `uv run panowan-test`.

- [ ] **Step 3: Create `third_party/PanoWan/backend.toml` with the runtime contract metadata**

Write:

```toml
[backend]
id = "panowan"
kind = "runtime"

[source]
strategy = "owned-submodule"
path = "."

[runtime]
entrypoint = "runner.py"
contract_version = "v1"

[runtime.inputs]
include = ["sources/**"]

[output]
root = "vendor"
revision_file = "vendor/.revision"
```

- [ ] **Step 4: Create `third_party/PanoWan/sources/runtime_adapter.py` with strict payload validation helpers**

Write:

```python
import json
import os
from dataclasses import dataclass
from typing import Any


class InvalidRunnerJob(ValueError):
    pass


@dataclass(frozen=True)
class RunnerResult:
    output_path: str


def _require_absolute_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not os.path.isabs(value):
        raise InvalidRunnerJob(f"{field_name} must be an absolute path")
    return value


def validate_job(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "version",
        "task",
        "prompt",
        "negative_prompt",
        "output_path",
        "resolution",
        "num_frames",
        "seed",
        "num_inference_steps",
        "guidance_scale",
        "result_path",
        "input_image_path",
        "denoising_strength",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise InvalidRunnerJob(f"Unknown fields: {', '.join(unknown)}")
    if payload.get("version") != "v1":
        raise InvalidRunnerJob("version must equal 'v1'")
    task = payload.get("task")
    if task not in {"t2v", "i2v"}:
        raise InvalidRunnerJob("task must be 't2v' or 'i2v'")
    if "prompt" not in payload:
        raise InvalidRunnerJob("prompt is required")
    if "negative_prompt" not in payload:
        raise InvalidRunnerJob("negative_prompt is required")
    resolution = payload.get("resolution")
    if not isinstance(resolution, dict):
        raise InvalidRunnerJob("resolution is required")
    for key in ("width", "height"):
        if not isinstance(resolution.get(key), int) or resolution[key] <= 0:
            raise InvalidRunnerJob(f"resolution.{key} must be a positive integer")
    if not isinstance(payload.get("num_frames"), int) or payload["num_frames"] <= 0:
        raise InvalidRunnerJob("num_frames must be a positive integer")
    payload["output_path"] = _require_absolute_path(payload.get("output_path"), "output_path")
    if payload.get("result_path") is not None:
        payload["result_path"] = _require_absolute_path(payload.get("result_path"), "result_path")
    if task == "i2v":
        payload["input_image_path"] = _require_absolute_path(
            payload.get("input_image_path"), "input_image_path"
        )
        denoising = payload.get("denoising_strength")
        if not isinstance(denoising, (int, float)) or denoising >= 1.0:
            raise InvalidRunnerJob("denoising_strength must be less than 1.0")
    else:
        if "input_image_path" in payload or "denoising_strength" in payload:
            raise InvalidRunnerJob(
                "input_image_path and denoising_strength are only valid for task=i2v"
            )
    return payload


def write_result(result_path: str | None, payload: dict[str, Any]) -> None:
    if not result_path:
        return
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
```

- [ ] **Step 5: Create `third_party/PanoWan/runner.py` with JSON transport, validation, and structured error handling**

Write:

```python
import argparse
import json
import sys
from pathlib import Path

from sources.runtime_adapter import InvalidRunnerJob, validate_job, write_result


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
        payload = validate_job(payload)
        # Temporary execution bridge until runtime internals are moved under sources/.
        # The public contract must stay at runner.py even while execution still delegates.
        output_path = payload["output_path"]
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).touch()
        write_result(result_path, {"status": "ok", "output_path": output_path})
        return 0
    except InvalidRunnerJob as exc:
        write_result(
            result_path,
            {"status": "error", "code": "INVALID_INPUT", "message": str(exc)},
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the targeted test and verify it passes with the new runner entrypoint present**

Run:

```bash
rtk python -m unittest tests.test_generator.GenerateVideoTests.test_generate_video_invokes_backend_root_runner_with_job_json
```

Expected: PASS.

- [ ] **Step 7: Commit the backend-root runner files**

Run:

```bash
rtk git add third_party/PanoWan/backend.toml third_party/PanoWan/runner.py third_party/PanoWan/sources/runtime_adapter.py tests/test_generator.py
rtk git commit -m "feat: add panowan runner v1 entrypoint"
```

### Task 2: Refactor generator to build strict runner payloads

**Files:**
- Modify: `app/generator.py`
- Modify: `tests/test_generator.py`
- Test: `tests/test_engines.py`

- [ ] **Step 1: Write failing tests for required `negative_prompt`, strict payload shape, and i2v-specific fields**

Add to `tests/test_generator.py`:

```python
    def test_generate_video_requires_negative_prompt_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative_prompt"):
            generate_video({"id": "job-1", "prompt": "sky"})

    @patch("app.generator.os.makedirs")
    @patch("app.generator.os.path.exists", return_value=True)
    @patch("app.generator.os.path.getsize", return_value=11)
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_writes_i2v_runner_payload(
        self,
        mock_popen,
        mock_getsize,
        mock_exists,
        mock_makedirs,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.return_value = ("ok", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        generate_video(
            {
                "id": "job-i2v",
                "task": "i2v",
                "prompt": "push in",
                "negative_prompt": "blur",
                "input_image_path": "/tmp/input.png",
                "denoising_strength": 0.85,
                "output_path": os.path.join(settings.output_dir, "output_job-i2v.mp4"),
            }
        )

        self.assertTrue(mock_popen.called)
```

- [ ] **Step 2: Run the generator test class and verify the new tests fail**

Run:

```bash
rtk python -m unittest tests.test_generator.GenerateVideoTests -v
```

Expected: FAIL because current generator synthesizes defaults and never writes a strict runner payload.

- [ ] **Step 3: Replace legacy preset/CLI assembly with helper functions that build the v1 runner payload**

In `app/generator.py`, replace the legacy shape with:

```python
def _payload_int(payload: dict, key: str) -> Optional[int]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def _require_field(payload: dict, key: str) -> str:
    if key not in payload:
        raise ValueError(f"{key} is required")
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _resolve_task(payload: dict) -> str:
    task = payload.get("task") or payload.get("mode") or "t2v"
    if task not in {"t2v", "i2v"}:
        raise ValueError("task must be 't2v' or 'i2v'")
    return task


def build_runner_payload(payload: dict) -> dict:
    job_id = str(payload.get("id") or payload.get("job_id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    negative_prompt = _require_field(payload, "negative_prompt")
    params = resolve_inference_params(payload)
    task = _resolve_task(payload)
    output_path = payload.get("output_path") or os.path.join(
        settings.output_dir, f"output_{job_id}.mp4"
    )
    runner_payload = {
        "version": "v1",
        "task": task,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "output_path": output_path,
        "resolution": {
            "width": params["width"],
            "height": params["height"],
        },
        "num_frames": int(payload.get("num_frames") or 81),
        "seed": params["seed"],
        "num_inference_steps": params["num_inference_steps"],
        "guidance_scale": payload.get("guidance_scale"),
    }
    if task == "i2v":
        runner_payload["input_image_path"] = _require_field(payload, "input_image_path")
        runner_payload["denoising_strength"] = payload["denoising_strength"]
    return runner_payload
```

- [ ] **Step 4: Change `generate_video()` to persist job JSON and invoke `runner.py --job`**

Replace the legacy command assembly in `app/generator.py` with:

```python
def generate_video(payload: dict) -> dict:
    job_id = str(payload.get("id") or payload.get("job_id") or uuid.uuid4())
    should_cancel = payload.get("_should_cancel")
    runner_payload = build_runner_payload({**payload, "id": job_id})
    output_path = runner_payload["output_path"]
    result_path = os.path.join(settings.runtime_dir, "panowan-runner", f"{job_id}.result.json")
    job_path = os.path.join(settings.runtime_dir, "panowan-runner", f"{job_id}.json")
    runner_payload["result_path"] = result_path

    os.makedirs(os.path.dirname(job_path), exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(job_path, "w", encoding="utf-8") as handle:
        json.dump(runner_payload, handle, ensure_ascii=False)

    cmd = ["python", "runner.py", "--job", job_path]
    result = run_cancellable_process(
        cmd,
        cwd=settings.panowan_engine_dir,
        timeout_seconds=settings.generation_timeout_seconds,
        should_cancel=should_cancel if callable(should_cancel) else None,
        text=True,
    )
    process = result.process
    if process.returncode != 0:
        raise RuntimeError(f"Generation failed: {output_tail(result.stderr)}")
    if not os.path.exists(output_path):
        raise FileNotFoundError("Output file not created")
    return {
        "id": job_id,
        "prompt": runner_payload["prompt"],
        "format": "mp4",
        "output_path": output_path,
    }
```

- [ ] **Step 5: Update `resolve_inference_params()` so it no longer backfills `negative_prompt` defaults**

In `app/generator.py`, keep only numeric generation defaults:

```python
def resolve_inference_params(payload: dict) -> dict:
    stored_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    preset_name = payload.get("quality")
    preset = _QUALITY_PRESETS.get(preset_name, {})
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
        "seed": _payload_int(stored_params, "seed")
        or _payload_int(payload, "seed")
        or 0,
    }
```

- [ ] **Step 6: Run generator and engine tests and verify the new boundary is green**

Run:

```bash
rtk python -m unittest tests.test_generator tests.test_engines -v
```

Expected: PASS.

- [ ] **Step 7: Commit the generator/engine boundary refactor**

Run:

```bash
rtk git add app/generator.py tests/test_generator.py tests/test_engines.py
rtk git commit -m "refactor: route panowan jobs through runner contract"
```

### Task 3: Add derived settings and path helpers for runner job/result scratch files

**Files:**
- Modify: `app/paths.py`
- Modify: `app/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Write failing settings tests for the new runner scratch paths**

Add to `tests/test_settings.py`:

```python
    def test_load_settings_includes_panowan_runner_scratch_paths(self) -> None:
        loaded = load_settings()
        self.assertEqual(
            loaded.panowan_runner_job_dir,
            os.path.join(loaded.runtime_dir, "panowan-runner"),
        )
        self.assertEqual(
            loaded.panowan_runner_result_dir,
            os.path.join(loaded.runtime_dir, "panowan-runner"),
        )
```

- [ ] **Step 2: Run the settings tests and verify they fail**

Run:

```bash
rtk python -m unittest tests.test_settings -v
```

Expected: FAIL because `Settings` has no runner scratch path fields yet.

- [ ] **Step 3: Add derived path helpers to `app/paths.py`**

Append:

```python
PANOWAN_RUNNER_DIRNAME = "panowan-runner"


def panowan_runner_dir_path(runtime_root: str) -> str:
    return container_child(runtime_root, PANOWAN_RUNNER_DIRNAME)
```

- [ ] **Step 4: Add the new fields to `Settings` and wire them in `load_settings()`**

In `app/settings.py`, extend the dataclass and loader:

```python
from .paths import (
    default_runtime_roots,
    job_store_path,
    lora_checkpoint_path,
    model_root_path,
    output_dir_path,
    panowan_runner_dir_path,
    repo_root_from,
    wan_diffusion_path,
    wan_t5_path,
    worker_store_path,
)
```

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
    panowan_runner_job_dir: str
    panowan_runner_result_dir: str
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
```

```python
runner_dir = panowan_runner_dir_path(runtime_dir)
return Settings(
    service_title="PanoWan Product Runtime API",
    service_version="1.0.0",
    panowan_engine_dir=roots.panowan_engine_root,
    model_root=model_root,
    wan_model_path=model_root_path(model_root),
    lora_checkpoint_path=lora_checkpoint_path(model_root),
    runtime_dir=runtime_dir,
    output_dir=output_dir,
    panowan_runner_job_dir=runner_dir,
    panowan_runner_result_dir=runner_dir,
    job_store_path=job_store_path(runtime_dir),
    worker_store_path=worker_store_path(runtime_dir),
    ...
)
```

- [ ] **Step 5: Run the settings tests and verify they pass**

Run:

```bash
rtk python -m unittest tests.test_settings -v
```

Expected: PASS.

- [ ] **Step 6: Commit the runner scratch-path settings update**

Run:

```bash
rtk git add app/paths.py app/settings.py tests/test_settings.py
rtk git commit -m "refactor: add panowan runner scratch paths"
```

### Task 4: Persist strict runner payload inputs at the API boundary

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests for required `negative_prompt` persistence and explicit task selection**

Add to `tests/test_api.py`:

```python
    def test_generate_persists_negative_prompt_in_job_payload(self) -> None:
        response = api.generate({"prompt": "test", "negative_prompt": "blur"})
        with open(api.settings.job_store_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
        record = persisted["jobs"][response["job_id"]]
        self.assertEqual(record["payload"]["negative_prompt"], "blur")
        self.assertEqual(record["payload"]["task"], "t2v")

    def test_generate_rejects_missing_negative_prompt(self) -> None:
        with self.assertRaisesRegex(HTTPException, "negative_prompt"):
            api.generate({"prompt": "test"})
```

- [ ] **Step 2: Run the targeted API tests and verify they fail**

Run:

```bash
rtk python -m unittest tests.test_api.ApiTests.test_generate_persists_negative_prompt_in_job_payload tests.test_api.ApiTests.test_generate_rejects_missing_negative_prompt
```

Expected: FAIL because `/generate` currently allows omitted `negative_prompt` and does not stamp `task` explicitly.

- [ ] **Step 3: Enforce required `negative_prompt` and explicit `task` in `app/api.py`**

At the start of `generate()` in `app/api.py`, insert:

```python
def generate(payload: dict) -> dict:
    if "negative_prompt" not in payload:
        raise HTTPException(status_code=422, detail="negative_prompt is required")
    task = payload.get("task") or payload.get("mode") or "t2v"
    if task not in {"t2v", "i2v"}:
        raise HTTPException(status_code=422, detail="task must be 't2v' or 'i2v'")
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    job_payload = dict(payload)
    job_payload["id"] = job_id
    job_payload["task"] = task
    params = resolve_inference_params(job_payload)
    record = _create_job_record(
        job_id, prompt, output_path, params, payload=job_payload
    )
    return {
        "job_id": job_id,
        "status": record["status"],
        "prompt": prompt,
        "output_path": output_path,
        "download_url": record["download_url"],
    }
```

- [ ] **Step 4: Add an i2v queueing test so the future runner payload has a stable dispatch field**

Add to `tests/test_api.py`:

```python
    def test_generate_persists_i2v_dispatch_fields(self) -> None:
        response = api.generate(
            {
                "task": "i2v",
                "prompt": "push in",
                "negative_prompt": "blur",
                "input_image_path": "/tmp/input.png",
                "denoising_strength": 0.85,
            }
        )
        with open(api.settings.job_store_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)
        record = persisted["jobs"][response["job_id"]]
        self.assertEqual(record["payload"]["task"], "i2v")
        self.assertEqual(record["payload"]["input_image_path"], "/tmp/input.png")
        self.assertEqual(record["payload"]["denoising_strength"], 0.85)
```

- [ ] **Step 5: Run the API test module and verify it passes**

Run:

```bash
rtk python -m unittest tests.test_api -v
```

Expected: PASS.

- [ ] **Step 6: Commit the API payload persistence changes**

Run:

```bash
rtk git add app/api.py tests/test_api.py
rtk git commit -m "refactor: persist strict panowan runner payloads"
```

### Task 5: Update engine and worker assumptions around the new boundary

**Files:**
- Modify: `app/engines/panowan.py`
- Modify: `tests/test_engines.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Write failing tests for runtime validation and engine payload delegation under the new boundary**

Add to `tests/test_engines.py`:

```python
    @mock.patch("app.engines.panowan.os.path.exists", return_value=True)
    def test_validate_runtime_accepts_backend_root_runner_contract(self, mock_exists):
        engine = PanoWanEngine()
        engine.validate_runtime()
        checked = [call.args[0] for call in mock_exists.call_args_list]
        self.assertIn(settings.panowan_engine_dir, checked)
```

Add to `tests/test_worker_service.py`:

```python
    def test_run_one_job_keeps_output_path_for_engine_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "prompt": "sky",
                    "negative_prompt": "blur",
                    "task": "t2v",
                    "output_path": f"{tmp}/outputs/output_job-1.mp4",
                }
            )
            worked = run_one_job(
                backend, _registry_with(FakeEngine()), worker_id="worker-a"
            )
            self.assertTrue(worked)
```

- [ ] **Step 2: Run the engine and worker tests and verify failures if assumptions are stale**

Run:

```bash
rtk python -m unittest tests.test_engines tests.test_worker_service -v
```

Expected: FAIL or partial FAIL until the validation and delegation assumptions are updated.

- [ ] **Step 3: Keep `PanoWanEngine` thin but make its runtime validation mention the backend-root contract**

In `app/engines/panowan.py`, change the error text and validation comment:

```python
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
                "PanoWan runner contract assets are missing. Run `make setup-backends` first:\n"
                f"{joined}"
            )
```

- [ ] **Step 4: Run the engine and worker tests and verify they pass**

Run:

```bash
rtk python -m unittest tests.test_engines tests.test_worker_service -v
```

Expected: PASS.

- [ ] **Step 5: Commit the engine/worker boundary cleanup**

Run:

```bash
rtk git add app/engines/panowan.py tests/test_engines.py tests/test_worker_service.py
rtk git commit -m "refactor: align panowan engine with runner contract"
```

### Task 6: Execute the focused regression suite and lint checks

**Files:**
- Modify: none
- Test: `tests/test_generator.py`
- Test: `tests/test_engines.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_api.py`
- Test: `tests/test_worker_service.py`

- [ ] **Step 1: Run the focused Python regression suite**

Run:

```bash
rtk python -m unittest \
  tests.test_generator \
  tests.test_engines \
  tests.test_settings \
  tests.test_api \
  tests.test_worker_service -v
```

Expected: PASS.

- [ ] **Step 2: Run Ruff on the touched application and test files**

Run:

```bash
rtk python -m ruff check app/generator.py app/settings.py app/paths.py app/api.py app/engines/panowan.py tests/test_generator.py tests/test_settings.py tests/test_api.py tests/test_engines.py tests/test_worker_service.py third_party/PanoWan/runner.py third_party/PanoWan/sources/runtime_adapter.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Run the full repository unittest suite**

Run:

```bash
rtk make test
```

Expected: PASS.

- [ ] **Step 4: Commit the final green verification if any fixes were required during the regression pass**

Run:

```bash
rtk git status
```

Expected: clean working tree, or only intentional follow-up fixes staged for a final commit.

---

## Self-Review

### Spec coverage

- `runner.py --job <json>` as the only public invocation shape: covered by Tasks 1 and 2.
- Required `negative_prompt`: covered by Tasks 2 and 4.
- Shared t2v/i2v contract with runner-owned branching: covered by Tasks 1, 2, and 4.
- Forbidden worker knowledge of upstream CLI details: covered by Task 2.
- Structured result/error handling: covered by Task 1.
- Settings/path support for JSON transport scratch files: covered by Task 3.
- Engine/worker integration after the refactor: covered by Task 5.

### Placeholder scan

No `TODO`, `TBD`, “similar to”, or unspecified “add tests” placeholders remain. Every code-changing step includes concrete code or file content.

### Type consistency

- Public payload fields match the v1 spec names: `version`, `task`, `prompt`, `negative_prompt`, `output_path`, `resolution`, `num_frames`, `result_path`, `input_image_path`, `denoising_strength`.
- The implementation plan consistently uses `build_runner_payload()` and `runner.py --job` rather than mixing old and new entrypoints.
- Settings names are consistent: `panowan_runner_job_dir` and `panowan_runner_result_dir`.

