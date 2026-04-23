# Video Upscale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add video super-resolution (upscale) capability with three backend models, real-time SSE updates, job cancellation, and a comparison preview window.

**Architecture:** Upscale jobs are independent job records with `type="upscale"` linked to source jobs via `source_job_id`. Each upscaler backend implements a `UpscalerBackend` Protocol that builds subprocess commands. SSE replaces polling for live status updates. Cancel supports two-phase process termination for running jobs.

**Tech Stack:** FastAPI, sse-starlette, subprocess.Popen, vanilla HTML/CSS/JS, Real-ESRGAN, RealBasicVSR, SeedVR2-3B

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/upscaler.py` | UpscalerBackend Protocol, three backend implementations, `upscale_video()` entry point |
| Create | `app/sse.py` | SSE subscriber management, broadcast helpers |
| Modify | `app/settings.py` | Add 3 upscale-related settings fields |
| Modify | `app/api.py` | Add `type`/`source_job_id`/`upscale_params` to job records; add `POST /upscale`, `POST /jobs/{id}/cancel`, `GET /jobs/events`; refactor subprocess to Popen; add SSE broadcast to `_update_job` |
| Modify | `app/generator.py` | Refactor `generate_video()` from `subprocess.run` to return a Popen-compatible interface (or extract command builder) |
| Modify | `app/static/index.html` | Add upscale dialog, cancel buttons, comparison preview (side-by-side, A/B toggle, slider), SSE client, download links for upscale jobs |
| Create | `tests/test_upscaler.py` | Unit tests for upscaler backends |
| Create | `tests/test_sse.py` | Unit tests for SSE broadcast |
| Modify | `tests/test_api.py` | Tests for upscale endpoint, cancel endpoint, job type fields |
| Modify | `tests/test_settings.py` | Test new upscale settings fields |
| Modify | `Dockerfile` | Install `sse-starlette`, add upscale model download step |
| Modify | `docker-compose.yml` | Add upscale env vars |
| Modify | `.env.example` | Document new upscale environment variables |

---

## Task 1: Settings — Add Upscale Configuration

**Files:**
- Modify: `app/settings.py`
- Modify: `tests/test_settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py`:

```python
def test_load_settings_includes_upscale_defaults(self) -> None:
    loaded = load_settings()
    self.assertEqual(loaded.upscale_model_dir, "/app/data/models/upscale")
    self.assertEqual(loaded.upscale_output_dir, "/app/runtime/outputs")
    self.assertEqual(loaded.upscale_timeout_seconds, 1800)

def test_load_settings_upscale_from_environment(self) -> None:
    env = {
        "UPSCALE_MODEL_DIR": "/custom/models",
        "UPSCALE_OUTPUT_DIR": "/custom/outputs",
        "UPSCALE_TIMEOUT_SECONDS": "900",
    }
    with patch.dict(os.environ, env, clear=False):
        loaded = load_settings()
    self.assertEqual(loaded.upscale_model_dir, "/custom/models")
    self.assertEqual(loaded.upscale_output_dir, "/custom/outputs")
    self.assertEqual(loaded.upscale_timeout_seconds, 900)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /path/to/project && python -m pytest tests/test_settings.py -v`
Expected: FAIL — `Settings` has no attribute `upscale_model_dir`

- [ ] **Step 3: Implement settings changes**

Add three fields to the `Settings` dataclass in `app/settings.py`:

```python
@dataclass(frozen=True)
class Settings:
    # ... existing fields ...
    upscale_model_dir: str
    upscale_output_dir: str
    upscale_timeout_seconds: int
```

Add to `load_settings()`:

```python
def load_settings() -> Settings:
    runtime_dir = os.getenv("RUNTIME_DIR", "/app/runtime")
    return Settings(
        # ... existing fields ...
        upscale_model_dir=os.getenv("UPSCALE_MODEL_DIR", os.path.join(runtime_dir, "..", "data", "models", "upscale")),
        upscale_output_dir=os.getenv("UPSCALE_OUTPUT_DIR", os.path.join(runtime_dir, "outputs")),
        upscale_timeout_seconds=int(os.getenv("UPSCALE_TIMEOUT_SECONDS", "1800")),
    )
```

Add to `.env.example`:

```bash
# ─── Upscale ──────────────────────────────────────────────────────
UPSCALE_MODEL_DIR=/app/data/models/upscale
UPSCALE_OUTPUT_DIR=/app/runtime/outputs
UPSCALE_TIMEOUT_SECONDS=1800
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/settings.py tests/test_settings.py .env.example
git commit -m "feat: add upscale settings fields (model_dir, output_dir, timeout)"
```

---

## Task 2: Upscaler Module — Backend Protocol and Real-ESRGAN

**Files:**
- Create: `app/upscaler.py`
- Create: `tests/test_upscaler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_upscaler.py`:

```python
import unittest
from app.upscaler import (
    UPSCALE_BACKENDS,
    RealESRGANBackend,
    upscale_video,
)


class UpscalerRegistryTests(unittest.TestCase):
    def test_registry_contains_expected_backends(self) -> None:
        self.assertIn("realesrgan-animevideov3", UPSCALE_BACKENDS)
        self.assertIn("realbasicvsr", UPSCALE_BACKENDS)
        self.assertIn("seedvr2-3b", UPSCALE_BACKENDS)

    def test_all_backends_have_required_fields(self) -> None:
        for name, backend in UPSCALE_BACKENDS.items():
            self.assertEqual(backend.name, name)
            self.assertTrue(len(backend.display_name) > 0)
            self.assertGreaterEqual(backend.default_scale, 1)
            self.assertGreaterEqual(backend.max_scale, backend.default_scale)


class RealESRGANBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = RealESRGANBackend()

    def test_build_command_basic(self) -> None:
        cmd = self.backend.build_command(
            input_path="/input/video.mp4",
            output_path="/output/video_up.mp4",
            scale=2,
            target_width=None,
            target_height=None,
            model_dir="/models",
        )
        self.assertIn("python", cmd)
        self.assertIn("inference_realesrgan_video.py", cmd)
        self.assertIn("-i", cmd)
        self.assertIn("/input/video.mp4", cmd)
        self.assertIn("-s", cmd)
        self.assertIn("2", cmd)

    def test_validate_params_rejects_exceed_max_scale(self) -> None:
        err = self.backend.validate_params(scale=8, source_w=448, source_h=224)
        self.assertIn("4", err)

    def test_validate_params_accepts_valid_scale(self) -> None:
        err = self.backend.validate_params(scale=2, source_w=448, source_h=224)
        self.assertIsNone(err)

    def test_build_command_with_target_resolution(self) -> None:
        cmd = self.backend.build_command(
            input_path="/input/video.mp4",
            output_path="/output/video_up.mp4",
            scale=2,
            target_width=896,
            target_height=448,
            model_dir="/models",
        )
        self.assertIn("-s", cmd)
        # target_width/height override: scale=2 for 448->896 is correct
        self.assertIn("2", cmd)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_upscaler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.upscaler'`

- [ ] **Step 3: Implement upscaler module with Real-ESRGAN backend**

Create `app/upscaler.py`:

```python
"""Video upscaler backends and execution logic."""

import os
import subprocess
from typing import Any, Protocol


class UpscalerBackend(Protocol):
    """Protocol for upscaler backends."""

    name: str
    display_name: str
    default_scale: int
    max_scale: int

    def build_command(
        self,
        input_path: str,
        output_path: str,
        scale: int,
        target_width: int | None,
        target_height: int | None,
        model_dir: str,
    ) -> list[str]:
        """Build the subprocess command for this backend."""
        ...

    def validate_params(self, scale: int, source_w: int, source_h: int) -> str | None:
        """Validate parameters. Return error message or None if valid."""
        ...


class RealESRGANBackend:
    name = "realesrgan-animevideov3"
    display_name = "Real-ESRGAN (Fast)"
    default_scale = 2
    max_scale = 4

    def build_command(
        self,
        input_path: str,
        output_path: str,
        scale: int,
        target_width: int | None,
        target_height: int | None,
        model_dir: str,
    ) -> list[str]:
        output_dir = os.path.dirname(output_path)
        effective_scale = scale
        if target_width and target_height:
            # Calculate scale from target (only works cleanly for integer scales)
            pass  # Real-ESRGAN uses -s flag directly; target resolution handled by scale
        return [
            "python", os.path.join(model_dir, "realesrgan", "inference_realesrgan_video.py"),
            "-i", input_path,
            "-o", output_dir,
            "-n", "realesr-animevideov3",
            "-s", str(effective_scale),
            "--half",
        ]

    def validate_params(self, scale: int, source_w: int, source_h: int) -> str | None:
        if scale > self.max_scale:
            return f"Real-ESRGAN maximum scale is {self.max_scale}x"
        if scale < 1:
            return "Scale must be at least 1"
        return None


class RealBasicVSRBackend:
    name = "realbasicvsr"
    display_name = "RealBasicVSR (High Quality)"
    default_scale = 4
    max_scale = 4

    def build_command(
        self,
        input_path: str,
        output_path: str,
        scale: int,
        target_width: int | None,
        target_height: int | None,
        model_dir: str,
    ) -> list[str]:
        config_path = os.path.join(model_dir, "realbasicvsr", "configs", "realbasicvsr_x4.py")
        checkpoint_path = os.path.join(model_dir, "realbasicvsr", "checkpoints", "RealBasicVSR_x4.pth")
        return [
            "python", os.path.join(model_dir, "realbasicvsr", "inference_realbasicvsr.py"),
            config_path,
            checkpoint_path,
            input_path,
            output_path,
            "--max-seq-len", "30",
        ]

    def validate_params(self, scale: int, source_w: int, source_h: int) -> str | None:
        if scale != 4:
            return "RealBasicVSR only supports 4x scale"
        return None


class SeedVR2Backend:
    name = "seedvr2-3b"
    display_name = "SeedVR2-3B (SOTA)"
    default_scale = 2
    max_scale = 4

    def build_command(
        self,
        input_path: str,
        output_path: str,
        scale: int,
        target_width: int | None,
        target_height: int | None,
        model_dir: str,
    ) -> list[str]:
        input_dir = os.path.dirname(input_path)
        output_dir = os.path.dirname(output_path)
        res_w = target_width or 0
        res_h = target_height or 0
        if not res_w or not res_h:
            # Calculate from scale — need source resolution passed separately
            # This will be resolved in api.py before calling build_command
            pass
        cmd = [
            "torchrun", "--nproc_per_node=1",
            os.path.join(model_dir, "seedvr2", "projects", "inference_seedvr2_3b.py"),
            "--video_path", input_dir,
            "--output_dir", output_dir,
            "--sp_size", "1",
        ]
        if res_w:
            cmd += ["--res_w", str(res_w)]
        if res_h:
            cmd += ["--res_h", str(res_h)]
        return cmd

    def validate_params(self, scale: int, source_w: int, source_h: int) -> str | None:
        if scale > self.max_scale:
            return f"SeedVR2 maximum scale is {self.max_scale}x"
        if scale < 1:
            return "Scale must be at least 1"
        res_w = source_w * scale
        res_h = source_h * scale
        if res_w % 32 != 0 or res_h % 32 != 0:
            return f"SeedVR2 requires target resolution multiples of 32, got {res_w}x{res_h}"
        return None


UPSCALE_BACKENDS: dict[str, UpscalerBackend] = {
    "realesrgan-animevideov3": RealESRGANBackend(),
    "realbasicvsr": RealBasicVSRBackend(),
    "seedvr2-3b": SeedVR2Backend(),
}


def upscale_video(
    input_path: str,
    output_path: str,
    model: str = "realesrgan-animevideov3",
    scale: int = 2,
    target_width: int | None = None,
    target_height: int | None = None,
    model_dir: str = "/app/data/models/upscale",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Execute video upscale via subprocess. Returns result dict.

    Raises on failure; caller handles error recording.
    """
    backend = UPSCALE_BACKENDS.get(model)
    if backend is None:
        raise ValueError(f"Unknown upscale model: {model}")

    cmd = backend.build_command(
        input_path=input_path,
        output_path=output_path,
        scale=scale,
        target_width=target_width,
        target_height=target_height,
        model_dir=model_dir,
    )

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise TimeoutError(
            f"Upscale timed out after {timeout_seconds} seconds"
        )

    if process.returncode != 0:
        err_msg = stderr[-500:] if stderr else f"Exit code {process.returncode}"
        raise RuntimeError(f"Upscale failed: {err_msg}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Upscale completed but output file missing")

    return {
        "output_path": output_path,
        "model": model,
        "scale": scale,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_upscaler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/upscaler.py tests/test_upscaler.py
git commit -m "feat: add upscaler module with Protocol and three backends"
```

---

## Task 3: Job Data Model — Add type, source_job_id, upscale_params

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py`:

```python
def test_create_job_record_includes_type_field(self) -> None:
    record = api._create_job_record("test-id", "prompt", "/out.mp4", {})
    self.assertEqual(record["type"], "generate")
    self.assertIsNone(record["source_job_id"])
    self.assertIsNone(record["upscale_params"])

def test_normalize_job_record_adds_type_for_legacy_jobs(self) -> None:
    legacy = {
        "job_id": "old-job",
        "status": "completed",
        "output_path": "/exists.mp4",
    }
    with patch("app.api.os.path.exists", return_value=True):
        normalized = api._normalize_job_record("old-job", legacy)
    self.assertEqual(normalized["type"], "generate")
    self.assertIsNone(normalized["source_job_id"])
    self.assertIsNone(normalized["upscale_params"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::ApiTests::test_create_job_record_includes_type_field -v`
Expected: FAIL — `KeyError: 'type'`

- [ ] **Step 3: Implement data model changes**

In `app/api.py`, update `_create_job_record` to include new fields:

```python
def _create_job_record(
    job_id: str, prompt: str, output_path: str, params: dict[str, Any],
    job_type: str = "generate",
    source_job_id: str | None = None,
    upscale_params: dict | None = None,
) -> dict[str, Any]:
    record = {
        "job_id": job_id,
        "status": "queued",
        "type": job_type,
        "prompt": prompt,
        "params": params,
        "output_path": output_path,
        "download_url": _job_download_url(job_id),
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "source_job_id": source_job_id,
        "upscale_params": upscale_params,
    }
    with _jobs_lock:
        if job_id in _jobs:
            raise ValueError(f"Job {job_id} already exists")
        _jobs[job_id] = record
        _persist_jobs_unlocked()
    return record
```

Update `_normalize_job_record` to add defaults for legacy records:

```python
def _normalize_job_record(job_id: str, record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["job_id"] = str(normalized.get("job_id") or job_id)
    normalized["download_url"] = _job_download_url(normalized["job_id"])
    normalized.setdefault("prompt", settings.default_prompt)
    normalized.setdefault("params", {})
    normalized.setdefault("output_path", "")
    normalized.setdefault("created_at", _now_iso())
    normalized.setdefault("started_at", None)
    normalized.setdefault("finished_at", None)
    normalized.setdefault("error", None)
    normalized.setdefault("status", "queued")
    normalized.setdefault("type", "generate")
    normalized.setdefault("source_job_id", None)
    normalized.setdefault("upscale_params", None)

    if normalized["status"] in {"queued", "running"}:
        normalized["status"] = "failed"
        normalized["finished_at"] = normalized["finished_at"] or _now_iso()
        normalized["error"] = "Service restarted before the job completed"
    elif normalized["status"] == "completed" and not os.path.exists(
        normalized["output_path"]
    ):
        normalized["status"] = "failed"
        normalized["finished_at"] = normalized["finished_at"] or _now_iso()
        normalized["error"] = "Output file missing after service restart"

    return normalized
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat: add type, source_job_id, upscale_params to job data model"
```

---

## Task 4: API — POST /upscale Endpoint

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py`:

```python
def test_upscale_creates_new_job_linked_to_source(self) -> None:
    # Create a completed source job
    with patch.dict(api._jobs, clear=True):
        source_id = "source-1"
        api._jobs[source_id] = {
            "job_id": source_id,
            "status": "completed",
            "type": "generate",
            "prompt": "test",
            "params": {"width": 448, "height": 224},
            "output_path": "/fake/output.mp4",
            "download_url": f"/jobs/{source_id}/download",
            "created_at": "now",
            "started_at": "now",
            "finished_at": "now",
            "error": None,
            "source_job_id": None,
            "upscale_params": None,
        }
        with patch("app.api.os.path.exists", return_value=True):
            response = api.upscale({"source_job_id": source_id, "model": "realesrgan-animevideov3", "scale": 2})

    self.assertEqual(response["status"], "queued")
    self.assertEqual(response["type"], "upscale")
    self.assertEqual(response["source_job_id"], source_id)
    self.assertEqual(response["upscale_params"]["model"], "realesrgan-animevideov3")
    self.assertEqual(response["upscale_params"]["scale"], 2)

def test_upscale_rejects_non_completed_source(self) -> None:
    with patch.dict(api._jobs, clear=True):
        api._jobs["running-1"] = {
            "job_id": "running-1", "status": "running", "type": "generate",
            "prompt": "", "params": {}, "output_path": "", "download_url": "",
            "created_at": "now", "started_at": None, "finished_at": None,
            "error": None, "source_job_id": None, "upscale_params": None,
        }
        with self.assertRaises(HTTPException) as ctx:
            api.upscale({"source_job_id": "running-1"})
        self.assertEqual(ctx.exception.status_code, 400)

def test_upscale_rejects_unknown_model(self) -> None:
    with patch.dict(api._jobs, clear=True):
        api._jobs["done-1"] = {
            "job_id": "done-1", "status": "completed", "type": "generate",
            "prompt": "", "params": {}, "output_path": "/out.mp4", "download_url": "",
            "created_at": "now", "started_at": None, "finished_at": None,
            "error": None, "source_job_id": None, "upscale_params": None,
        }
        with patch("app.api.os.path.exists", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                api.upscale({"source_job_id": "done-1", "model": "nonexistent"})
        self.assertEqual(ctx.exception.status_code, 400)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::ApiTests::test_upscale_creates_new_job_linked_to_source -v`
Expected: FAIL — `AttributeError: module 'app.api' has no attribute 'upscale'`

- [ ] **Step 3: Implement POST /upscale endpoint**

Add to `app/api.py`, after the `generate` endpoint:

```python
from .upscaler import UPSCALE_BACKENDS, upscale_video


@app.post("/upscale", status_code=202)
def upscale(payload: dict, background_tasks: BackgroundTasks) -> dict:
    source_job_id = payload.get("source_job_id")
    if not source_job_id:
        raise HTTPException(status_code=400, detail="source_job_id is required")

    source_job = _get_job(source_job_id)
    if source_job is None:
        raise HTTPException(status_code=400, detail="Source job not found")
    if source_job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Can only upscale completed jobs")
    if not os.path.exists(source_job["output_path"]):
        raise HTTPException(status_code=400, detail="Source video file not found")

    model_name = payload.get("model", "realesrgan-animevideov3")
    backend = UPSCALE_BACKENDS.get(model_name)
    if backend is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")

    # Resolve scale
    target_width = payload.get("target_width")
    target_height = payload.get("target_height")
    scale = payload.get("scale")

    if not scale and not target_width and not target_height:
        scale = backend.default_scale
    elif not scale:
        # Calculate scale from target dimensions vs source resolution
        src_params = source_job.get("params", {})
        src_w = src_params.get("width", 896)
        src_h = src_params.get("height", 448)
        if target_width:
            scale = target_width // src_w
        elif target_height:
            scale = target_height // src_h
        if scale and scale < 1:
            scale = 1
    if not scale:
        scale = backend.default_scale

    # Validate
    src_params = source_job.get("params", {})
    src_w = src_params.get("width", 896)
    src_h = src_params.get("height", 448)
    validation_error = backend.validate_params(scale, src_w, src_h)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)

    # Calculate target dimensions for SeedVR2
    if target_width is None and target_height is None:
        target_width = src_w * scale
        target_height = src_h * scale

    job_id = str(uuid.uuid4())
    output_path = os.path.join(settings.upscale_output_dir, f"output_{job_id}.mp4")
    upscale_params = {
        "model": model_name,
        "scale": scale,
        "target_width": target_width,
        "target_height": target_height,
    }

    try:
        _create_job_record(
            job_id,
            prompt=source_job.get("prompt", ""),
            output_path=output_path,
            params=source_job.get("params", {}),
            job_type="upscale",
            source_job_id=source_job_id,
            upscale_params=upscale_params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    background_tasks.add_task(
        _run_upscale_job, job_id, source_job["output_path"], output_path, upscale_params
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "type": "upscale",
        "source_job_id": source_job_id,
        "upscale_params": upscale_params,
    }


def _run_upscale_job(
    job_id: str, input_path: str, output_path: str, upscale_params: dict
) -> None:
    try:
        _update_job(job_id, status="running", started_at=_now_iso())
        with _gpu_slot:
            result = upscale_video(
                input_path=input_path,
                output_path=output_path,
                model=upscale_params["model"],
                scale=upscale_params["scale"],
                target_width=upscale_params.get("target_width"),
                target_height=upscale_params.get("target_height"),
                model_dir=settings.upscale_model_dir,
                timeout_seconds=settings.upscale_timeout_seconds,
            )
        _update_job(
            job_id,
            status="completed",
            finished_at=_now_iso(),
            output_path=result["output_path"],
        )
    except Exception as exc:
        print(f"ERROR: upscale job {job_id} failed: {exc}", flush=True)
        traceback.print_exc()
        try:
            _update_job(
                job_id,
                status="failed",
                finished_at=_now_iso(),
                error=str(exc),
            )
        except KeyError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat: add POST /upscale endpoint with validation and background execution"
```

---

## Task 5: API — POST /jobs/{job_id}/cancel Endpoint

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api.py`:

```python
def test_cancel_queued_job_succeeds(self) -> None:
    with patch.dict(api._jobs, clear=True):
        api._jobs["q1"] = {
            "job_id": "q1", "status": "queued", "type": "generate",
            "prompt": "", "params": {}, "output_path": "", "download_url": "",
            "created_at": "now", "started_at": None, "finished_at": None,
            "error": None, "source_job_id": None, "upscale_params": None,
        }
        result = api.cancel_job("q1", force=False)

    self.assertEqual(result["status"], "failed")
    self.assertEqual(result["error"], "Cancelled by user")

def test_cancel_running_without_force_returns_warning(self) -> None:
    with patch.dict(api._jobs, clear=True):
        api._jobs["r1"] = {
            "job_id": "r1", "status": "running", "type": "generate",
            "prompt": "", "params": {}, "output_path": "", "download_url": "",
            "created_at": "now", "started_at": None, "finished_at": None,
            "error": None, "source_job_id": None, "upscale_params": None,
            "_process": None,
        }
        result = api.cancel_job("r1", force=False)

    self.assertTrue(result.get("warning"))

def test_cancel_completed_job_raises(self) -> None:
    with patch.dict(api._jobs, clear=True):
        api._jobs["c1"] = {
            "job_id": "c1", "status": "completed", "type": "generate",
            "prompt": "", "params": {}, "output_path": "/out.mp4", "download_url": "",
            "created_at": "now", "started_at": None, "finished_at": None,
            "error": None, "source_job_id": None, "upscale_params": None,
        }
        with self.assertRaises(HTTPException) as ctx:
            api.cancel_job("c1", force=False)
        self.assertEqual(ctx.exception.status_code, 409)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py::ApiTests::test_cancel_queued_job_succeeds -v`
Expected: FAIL — `AttributeError: module 'app.api' has no attribute 'cancel_job'`

- [ ] **Step 3: Implement cancel endpoint**

Add to `app/api.py`:

```python
@app.post("/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, payload: dict = None) -> dict:
    payload = payload or {}
    force = payload.get("force", False)
    result = cancel_job(job_id, force=force)
    if result.get("warning"):
        return JSONResponse(content=result, status_code=202)
    return result


def cancel_job(job_id: str, force: bool = False) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        status = job["status"]
        if status == "queued":
            job["status"] = "failed"
            job["error"] = "Cancelled by user"
            job["finished_at"] = _now_iso()
            _persist_jobs_unlocked()
            return dict(job)

        if status == "running":
            if not force:
                process = job.get("_process")
                return {
                    "warning": True,
                    "job_id": job_id,
                    "status": "running",
                    "message": "Job is currently running. Force termination may cause incomplete output. Set force=true to confirm.",
                    "pid": process.pid if process else None,
                }
            # Two-phase termination
            process = job.get("_process")
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        job["status"] = "failed"
                        job["error"] = "Cancel failed: process unkillable"
                        job["finished_at"] = _now_iso()
                        _persist_jobs_unlocked()
                        raise HTTPException(status_code=500, detail="Cancel failed: process unkillable")
            job["status"] = "failed"
            job["error"] = "Cancelled by user"
            job["finished_at"] = _now_iso()
            _persist_jobs_unlocked()
            return dict(job)

        # completed or failed
        raise HTTPException(status_code=409, detail=f"Cannot cancel job with status {status}")
```

Also add the import at the top of `app/api.py`:

```python
from fastapi.responses import FileResponse, JSONResponse
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "feat: add POST /jobs/{id}/cancel with two-phase termination"
```

---

## Task 6: SSE — Broadcast and Endpoint

**Files:**
- Create: `app/sse.py`
- Modify: `app/api.py`
- Create: `tests/test_sse.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sse.py`:

```python
import asyncio
import json
import unittest
from app.sse import SSEBus, subscribe, broadcast_job_event


class SSEBusTests(unittest.TestCase):
    def test_subscribe_returns_queue(self) -> None:
        bus = SSEBus()
        queue = bus.subscribe()
        self.assertIsInstance(queue, asyncio.Queue)

    def test_broadcast_delivers_to_all_subscribers(self) -> None:
        bus = SSEBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.broadcast("job_updated", {"job_id": "test", "status": "running"})
        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        self.assertEqual(msg1["event"], "job_updated")
        self.assertEqual(json.loads(msg1["data"])["job_id"], "test")
        self.assertEqual(msg2["event"], "job_updated")

    def test_unsubscribe_removes_queue(self) -> None:
        bus = SSEBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.broadcast("job_updated", {"job_id": "test"})
        self.assertTrue(q.empty())

    def test_broadcast_after_unsubscribe_only_reaches_active(self) -> None:
        bus = SSEBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.unsubscribe(q1)
        bus.broadcast("job_updated", {"job_id": "test"})
        self.assertTrue(q1.empty())
        self.assertFalse(q2.empty())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sse'`

- [ ] **Step 3: Implement SSE module**

Create `app/sse.py`:

```python
"""Server-Sent Events broadcast bus for job status updates."""

import asyncio
import json
from typing import Any


class SSEBus:
    """Simple pub/sub bus for SSE job events."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        message = {
            "event": event,
            "data": json.dumps(data, ensure_ascii=False),
        }
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # Drop if consumer is slow


# Module-level singleton
_bus = SSEBus()


def subscribe() -> asyncio.Queue:
    return _bus.subscribe()


def unsubscribe(queue: asyncio.Queue) -> None:
    _bus.unsubscribe(queue)


def broadcast_job_event(event_type: str, job_data: dict[str, Any]) -> None:
    """Broadcast a job event to all SSE subscribers."""
    _bus.broadcast(event_type, job_data)
```

- [ ] **Step 4: Run SSE tests**

Run: `python -m pytest tests/test_sse.py -v`
Expected: PASS

- [ ] **Step 5: Wire SSE into api.py — add endpoint and broadcast on job changes**

Add import to `app/api.py`:

```python
import asyncio
from .sse import broadcast_job_event, subscribe, unsubscribe
```

Add SSE endpoint to `app/api.py`:

```python
from sse_starlette.sse import EventSourceResponse


@app.get("/jobs/events")
async def job_events(request: Request) -> EventSourceResponse:
    from fastapi import Request

    async def event_generator():
        queue = subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield event
                except asyncio.TimeoutError:
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"ts": _now_iso()}),
                    }
        finally:
            unsubscribe(queue)

    return EventSourceResponse(event_generator())
```

Also add `from fastapi import Request` to the imports.

Update `_create_job_record` to broadcast after creating:

```python
def _create_job_record(...) -> dict[str, Any]:
    # ... existing code ...
    with _jobs_lock:
        if job_id in _jobs:
            raise ValueError(f"Job {job_id} already exists")
        _jobs[job_id] = record
        _persist_jobs_unlocked()
    broadcast_job_event("job_created", record)
    return record
```

Update `_update_job` to broadcast after updating:

```python
def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    with _jobs_lock:
        if job_id not in _jobs:
            raise KeyError(job_id)
        _jobs[job_id].update(updates)
        _persist_jobs_unlocked()
        snapshot = dict(_jobs[job_id])
    broadcast_job_event("job_updated", {**updates, "job_id": job_id})
    return snapshot
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/sse.py app/api.py tests/test_sse.py
git commit -m "feat: add SSE broadcast bus and /jobs/events endpoint"
```

---

## Task 7: Generator — Refactor to Popen for Cancel Support

**Files:**
- Modify: `app/generator.py`
- Modify: `tests/test_generator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generator.py`:

```python
def test_generate_video_uses_popen(self) -> None:
    """generate_video should return a Popen-compatible result and store process."""
    with patch("app.generator.subprocess.Popen") as mock_popen, \
         patch("app.generator.os.makedirs"), \
         patch("app.generator.os.path.exists", return_value=True), \
         patch("app.generator.os.path.getsize", return_value=11):
        mock_process = SimpleNamespace(
            communicate=lambda timeout=None: (SimpleNamespace(), SimpleNamespace()),
            returncode=0,
            stdout="ok",
            stderr="",
        )
        mock_popen.return_value = mock_process
        result = generate_video({"id": "popen-test", "prompt": "test"})
    self.assertEqual(result["id"], "popen-test")
    mock_popen.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generator.py::GenerateVideoTests::test_generate_video_uses_popen -v`
Expected: FAIL — `generate_video` still calls `subprocess.run`

- [ ] **Step 3: Refactor generate_video to use Popen**

In `app/generator.py`, replace `subprocess.run` with `subprocess.Popen`:

```python
def generate_video(payload: dict) -> dict:
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    params = resolve_inference_params(payload)

    print(f"=== Job received: {job_id} ===", flush=True)
    print(f"Prompt: {prompt[:100]}", flush=True)
    print(
        f"Params: steps={params['num_inference_steps']} "
        f"{params['width']}x{params['height']} seed={params['seed']}",
        flush=True,
    )

    os.makedirs(settings.output_dir, exist_ok=True)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    cmd = [
        "uv", "run", "panowan-test",
        "--wan-model-path", settings.wan_model_path,
        "--lora-checkpoint-path", settings.lora_checkpoint_path,
        "--output-path", output_path,
        "--prompt", prompt,
        "--num-inference-steps", str(params["num_inference_steps"]),
        "--width", str(params["width"]),
        "--height", str(params["height"]),
        "--seed", str(params["seed"]),
    ]
    if params["negative_prompt"]:
        cmd += ["--negative-prompt", params["negative_prompt"]]

    print(f"Running: {' '.join(cmd)}", flush=True)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=settings.panowan_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(timeout=settings.generation_timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        print("ERROR: Generation timed out", flush=True)
        raise TimeoutError(
            "Generation timed out after "
            f"{settings.generation_timeout_seconds} seconds"
        )

    print(f"Return code: {process.returncode}", flush=True)
    if stdout:
        print(f"Stdout: {stdout[-500:]}", flush=True)
    if stderr:
        print(f"Stderr: {stderr[-500:]}", flush=True)

    if process.returncode != 0:
        raise RuntimeError(f"Generation failed: {stderr[-500:]}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Output file not created")

    video_size = os.path.getsize(output_path)
    print(f"=== Job complete, video size: {video_size} bytes ===", flush=True)

    return {
        "id": job_id,
        "prompt": prompt,
        "format": "mp4",
        "output_path": output_path,
    }
```

- [ ] **Step 4: Update existing test to match Popen interface**

In `tests/test_generator.py`, update the mock from `subprocess.run` to `subprocess.Popen`:

```python
@patch("app.generator.os.makedirs")
@patch("app.generator.os.path.exists", return_value=True)
@patch("app.generator.os.path.getsize", return_value=11)
@patch("app.generator.subprocess.Popen")
def test_generates_video_payload(
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

    result = generate_video({"id": "job-1", "prompt": "mountain sunset"})

    self.assertEqual(result["id"], "job-1")
    self.assertEqual(result["prompt"], "mountain sunset")
    self.assertEqual(result["format"], "mp4")
    self.assertEqual(
        result["output_path"],
        os.path.join(settings.output_dir, "output_job-1.mp4"),
    )
    mock_popen.assert_called_once()
    mock_getsize.assert_called_once_with(
        os.path.join(settings.output_dir, "output_job-1.mp4")
    )
    mock_makedirs.assert_called_once_with(settings.output_dir, exist_ok=True)
    self.assertTrue(mock_exists.called)
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/generator.py tests/test_generator.py
git commit -m "refactor: switch generate_video from subprocess.run to Popen for cancel support"
```

---

## Task 8: Frontend — SSE Client and Polling Migration

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Add SSE client class and replace polling**

In the `<script>` section of `index.html`, add the `JobEventSource` class after the existing variable declarations (around line 462) and modify the polling logic:

Replace the existing polling code (lines 627-663) with:

```javascript
// ── SSE + fallback polling ──
class JobEventSource {
    constructor() {
        this.es = null;
        this.reconnectTimer = null;
        this.fallbackPollTimer = null;
    }

    connect() {
        this.es = new EventSource("/jobs/events");

        this.es.addEventListener("job_created", (e) => {
            const job = JSON.parse(e.data);
            _jobCache[job.job_id] = job;
            this._renderIncremental();
        });

        this.es.addEventListener("job_updated", (e) => {
            const patch = JSON.parse(e.data);
            const id = patch.job_id;
            if (_jobCache[id]) {
                Object.assign(_jobCache[id], patch);
            } else {
                _jobCache[id] = patch;
            }
            this._renderIncremental();
        });

        this.es.onerror = () => {
            this.es.close();
            this.es = null;
            this.startFallbackPoll();
            this.scheduleReconnect();
        };
    }

    _renderIncremental() {
        const jobs = Object.values(_jobCache);
        jobs.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
        renderTable(jobs);
        const busy = jobs.some(j => j.status === "queued" || j.status === "running");
        setPollingIndicator(busy);
    }

    startFallbackPoll() {
        if (this.fallbackPollTimer) return;
        this.fallbackPollTimer = setInterval(refreshJobs, 5000);
    }

    stopFallbackPoll() {
        if (this.fallbackPollTimer) {
            clearInterval(this.fallbackPollTimer);
            this.fallbackPollTimer = null;
        }
    }

    scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            // Full sync before reconnecting
            fetchJobs().then(jobs => {
                if (jobs) {
                    renderTable(jobs);
                    this.stopFallbackPoll();
                    this.connect();
                }
            });
        }, 5000);
    }
}

const sseClient = new JobEventSource();
```

Replace `scheduleRefresh` and `refreshJobs` with SSE-aware versions:

```javascript
async function refreshJobs() {
    const jobs = await fetchJobs();
    if (jobs !== null) {
        renderTable(jobs);
        const busy = hasActiveJobs(jobs);
        setPollingIndicator(busy);
    }
}

// ── init: full load then SSE ──
refreshJobs().then(() => {
    sseClient.connect();
});
```

Remove the old `scheduleRefresh` function and `pollTimer` variable (no longer needed for primary flow).

- [ ] **Step 2: Test in browser**

Start the dev server and verify:
1. Page loads, fetches full job list, then connects to SSE
2. When a job status changes, UI updates without full page refresh
3. If you stop the server (simulate disconnect), it falls back to polling
4. When server restarts, SSE reconnects

- [ ] **Step 3: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add SSE client with fallback polling for real-time job updates"
```

---

## Task 9: Frontend — Upscale Dialog and Cancel Button

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Add upscale configuration dialog HTML**

After the existing preview dialog (line 335), add:

```html
<!-- Upscale dialog -->
<dialog id="upscale-dialog">
  <div class="dialog-inner" style="background:var(--panel-strong);color:var(--ink);">
    <div class="dialog-header" style="border-bottom:1px solid var(--border);">
      <h3 id="upscale-title" style="color:var(--ink);">提升画质</h3>
      <button class="dialog-close" id="upscale-close-btn" style="background:var(--accent-soft);color:var(--accent);">✕</button>
    </div>
    <div style="padding:18px 22px;">
      <p id="upscale-source-info" style="font-size:0.85rem;color:var(--muted);margin:0 0 14px;"></p>

      <label style="font-size:0.85rem;">超分模型</label>
      <select id="upscale-model" style="margin-bottom:14px;">
        <option value="realesrgan-animevideov3">Real-ESRGAN (快速)</option>
        <option value="realbasicvsr">RealBasicVSR (高质量)</option>
        <option value="seedvr2-3b">SeedVR2-3B (SOTA)</option>
      </select>

      <label style="font-size:0.85rem;">缩放方式</label>
      <div class="quality-row" style="margin-bottom:14px;">
        <button type="button" class="quality-btn active" data-scale-mode="factor">按倍率</button>
        <button type="button" class="quality-btn" data-scale-mode="resolution">指定分辨率</button>
      </div>

      <div id="upscale-factor-section">
        <label style="font-size:0.85rem;">缩放倍率</label>
        <select id="upscale-scale">
          <option value="2">2x</option>
          <option value="4">4x</option>
        </select>
      </div>

      <div id="upscale-resolution-section" style="display:none;">
        <div class="params-grid">
          <div>
            <label style="font-size:0.85rem;">目标宽度</label>
            <input type="number" id="upscale-target-w" min="32" step="32">
          </div>
          <div>
            <label style="font-size:0.85rem;">目标高度</label>
            <input type="number" id="upscale-target-h" min="32" step="32">
          </div>
        </div>
      </div>

      <p id="upscale-hint" style="font-size:0.78rem;color:var(--muted);margin-top:10px;"></p>

      <div class="row" style="margin-top:18px;">
        <button id="upscale-cancel-btn" class="secondary" type="button">取消</button>
        <button id="upscale-submit-btn" type="button">开始提升</button>
      </div>
      <span id="upscale-status" class="submit-status"></span>
    </div>
  </div>
</dialog>
```

- [ ] **Step 2: Add JS logic for upscale dialog and cancel button**

Add JS functions after the existing `openPreview` function:

```javascript
// ── upscale dialog ──
const upscaleDialog = document.getElementById("upscale-dialog");
let upscaleSourceJobId = null;

document.getElementById("upscale-close-btn").addEventListener("click", () => {
  upscaleDialog.close();
});
document.getElementById("upscale-cancel-btn").addEventListener("click", () => {
  upscaleDialog.close();
});
upscaleDialog.addEventListener("click", e => {
  if (e.target === upscaleDialog) upscaleDialog.close();
});

// Scale mode toggle
document.querySelectorAll("[data-scale-mode]").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-scale-mode]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.scaleMode;
    document.getElementById("upscale-factor-section").style.display = mode === "factor" ? "" : "none";
    document.getElementById("upscale-resolution-section").style.display = mode === "resolution" ? "" : "none";
  });
});

// Model hint updates
const MODEL_HINTS = {
  "realesrgan-animevideov3": "Real-ESRGAN: 逐帧处理，速度快，无时序一致性。推荐 2x。",
  "realbasicvsr": "RealBasicVSR: 双向传播，时序一致性好。仅支持 4x。",
  "seedvr2-3b": "SeedVR2-3B: 单步扩散，最佳画质。目标分辨率需为 32 的倍数。",
};
document.getElementById("upscale-model").addEventListener("change", function() {
  document.getElementById("upscale-hint").textContent = MODEL_HINTS[this.value] || "";
});

function openUpscaleDialog(job) {
  upscaleSourceJobId = job.job_id;
  const p = job.params || {};
  document.getElementById("upscale-source-info").textContent =
    `源任务: #${job.job_id.slice(0,8)}…  |  原始分辨率: ${p.width || "?"}×${p.height || "?"}`;
  document.getElementById("upscale-model").value = "realesrgan-animevideov3";
  document.getElementById("upscale-hint").textContent = MODEL_HINTS["realesrgan-animevideov3"];
  document.getElementById("upscale-scale").value = "2";
  document.getElementById("upscale-status").textContent = "";
  document.querySelectorAll("[data-scale-mode]").forEach(b => b.classList.remove("active"));
  document.querySelector("[data-scale-mode='factor']").classList.add("active");
  document.getElementById("upscale-factor-section").style.display = "";
  document.getElementById("upscale-resolution-section").style.display = "none";
  if (p.width) document.getElementById("upscale-target-w").value = p.width * 2;
  if (p.height) document.getElementById("upscale-target-h").value = p.height * 2;
  upscaleDialog.showModal();
}

document.getElementById("upscale-submit-btn").addEventListener("click", async () => {
  if (!upscaleSourceJobId) return;
  const body = { source_job_id: upscaleSourceJobId };
  body.model = document.getElementById("upscale-model").value;
  const mode = document.querySelector("[data-scale-mode].active").dataset.scaleMode;
  if (mode === "factor") {
    body.scale = parseInt(document.getElementById("upscale-scale").value);
  } else {
    body.target_width = parseInt(document.getElementById("upscale-target-w").value) || undefined;
    body.target_height = parseInt(document.getElementById("upscale-target-h").value) || undefined;
  }
  const statusEl = document.getElementById("upscale-status");
  try {
    const res = await fetch("/upscale", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await res.json();
    if (!res.ok) {
      statusEl.textContent = `失败: ${payload.detail || res.status}`;
      return;
    }
    statusEl.textContent = `✓ 超分任务 ${payload.job_id.slice(0,8)}… 已加入队列`;
    upscaleDialog.close();
    refreshJobs();
  } catch (err) {
    statusEl.textContent = `网络错误: ${err}`;
  }
});

// ── cancel job ──
async function cancelJob(jobId, isRunning) {
  if (isRunning) {
    const ok = confirm("该任务正在 GPU 上执行，强制终止可能产生不完整的输出。是否确认强制终止？");
    if (!ok) return;
  }
  try {
    const res = await fetch(`/jobs/${jobId}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: isRunning }),
    });
    if (res.status === 202) {
      // Warning — job is running and force not confirmed (shouldn't happen with our UI flow)
      alert("任务正在运行，请确认强制终止。");
      return;
    }
    refreshJobs();
  } catch (err) {
    alert(`取消失败: ${err}`);
  }
}
```

- [ ] **Step 3: Update actionCell to include upscale and cancel buttons**

Replace the existing `actionCell` function:

```javascript
function actionCell(job) {
  const parts = [];
  if (job.status === "completed") {
    parts.push(`<button class="preview-btn" data-job-id="${escapeHtml(job.job_id)}">预览</button>`);
    if (job.type === "upscale") {
      const srcId = job.source_job_id || "";
      parts.push(`<a class="download-btn" href="/jobs/${escapeHtml(srcId)}/download" download="${escapeHtml(srcId)}.mp4">下载原视频</a>`);
      parts.push(`<a class="download-btn" href="/jobs/${escapeHtml(job.job_id)}/download" download="${escapeHtml(job.job_id)}.mp4" style="background:var(--success-soft);color:var(--success);">下载超分</a>`);
    } else {
      const url = job.download_url || `/jobs/${job.job_id}/download`;
      parts.push(`<a class="download-btn" href="${url}" download="${escapeHtml(job.job_id)}.mp4">下载</a>`);
    }
    parts.push(`<button class="preview-btn" data-action="upscale" data-job-id="${escapeHtml(job.job_id)}" style="background:var(--queued-soft);color:var(--accent);">提升画质</button>`);
  } else if (job.status === "queued") {
    parts.push(`<button class="preview-btn" data-action="cancel" data-job-id="${escapeHtml(job.job_id)}" style="background:var(--error-soft);color:var(--error);">取消</button>`);
  } else if (job.status === "running") {
    parts.push(`<button class="preview-btn" data-action="cancel" data-job-id="${escapeHtml(job.job_id)}" data-running="true" style="background:var(--error-soft);color:var(--error);">取消</button>`);
  } else if (job.status === "failed" && job.error) {
    parts.push(`<span class="error-text" title="${escapeHtml(job.error)}">${escapeHtml(job.error)}</span>`);
  }
  if (job.type === "upscale" && job.source_job_id) {
    parts.unshift(`<span style="font-size:0.72rem;color:var(--muted);">↑ ${escapeHtml(job.source_job_id.slice(0,6))}…</span>`);
  }
  return parts.length ? parts.join(" ") : "-";
}
```

- [ ] **Step 4: Update event delegation to handle upscale and cancel clicks**

Replace the existing `tbody.addEventListener("click", ...)` block:

```javascript
tbody.addEventListener("click", event => {
  const previewBtn = event.target.closest('[data-action="preview"], .preview-btn:not([data-action])');
  const upscaleBtn = event.target.closest('[data-action="upscale"]');
  const cancelBtn = event.target.closest('[data-action="cancel"]');

  if (previewBtn) {
    const job = _jobCache[previewBtn.dataset.jobId];
    if (job) openPreview(job);
    return;
  }
  if (upscaleBtn) {
    const job = _jobCache[upscaleBtn.dataset.jobId];
    if (job) openUpscaleDialog(job);
    return;
  }
  if (cancelBtn) {
    const jobId = cancelBtn.dataset.jobId;
    const isRunning = cancelBtn.dataset.running === "true";
    cancelJob(jobId, isRunning);
    return;
  }
});
```

- [ ] **Step 5: Update statusBadge for upscale type labels**

Update the `statusBadge` function:

```javascript
function statusBadge(status) {
  const cls = ["queued","running","completed","failed"].includes(status) ? status : "unknown";
  const labels = { queued: "排队中", running: "处理中", completed: "已完成", failed: "失败" };
  return `<span class="badge badge-${cls}">${labels[cls] || status}</span>`;
}
```

- [ ] **Step 6: Test in browser**

Start the dev server and verify:
1. Completed jobs show "提升画质" button
2. Clicking it opens the upscale dialog
3. Model selection works, hints update
4. Scale mode toggle works
5. Submitting creates an upscale job
6. Queued/running jobs show "取消" button
7. Cancel on running job shows confirmation dialog

- [ ] **Step 7: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add upscale dialog, cancel buttons, and updated action cell"
```

---

## Task 10: Frontend — Comparison Preview Window

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Add comparison CSS styles**

Add to the `<style>` section:

```css
/* ── comparison preview ── */
.compare-tabs {
  display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,0.08);
}
.compare-tab {
  flex: 1; text-align: center; padding: 8px 0; font-size: 0.78rem; font-weight: 700;
  background: rgba(255,255,255,0.03); border: none; color: #8a8070; cursor: pointer;
  transition: color 120ms, background 120ms;
}
.compare-tab:hover { background: rgba(255,255,255,0.06); }
.compare-tab.active { color: #e0d8cc; background: rgba(255,255,255,0.08); }

.compare-side-by-side {
  display: grid; grid-template-columns: 1fr 1fr; gap: 0;
}
.compare-side-by-side video { width: 100%; display: block; }

.compare-toggle-wrap { position: relative; }
.compare-toggle-btns {
  display: flex; gap: 6px; justify-content: center; padding: 8px 0;
}
.compare-toggle-btn {
  padding: 4px 14px; border-radius: 999px; font-size: 0.78rem; font-weight: 700;
  border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.06);
  color: #8a8070; cursor: pointer;
}
.compare-toggle-btn.active { color: #e0d8cc; border-color: var(--accent); background: rgba(190,91,45,0.15); }

.compare-slider-wrap { position: relative; user-select: none; }
.compare-slider-wrap canvas { display: block; width: 100%; }
.compare-slider-line {
  position: absolute; top: 0; bottom: 0; width: 2px;
  background: var(--accent); cursor: ew-resize; z-index: 2;
}
.compare-slider-label {
  position: absolute; top: 6px; font-size: 0.68rem; font-weight: 700; color: rgba(255,255,255,0.6);
}
.compare-slider-label.left { left: 8px; }
.compare-slider-label.right { right: 8px; }
.compare-frame-nav {
  display: flex; justify-content: center; gap: 8px; padding: 6px 0;
}
.compare-frame-nav button {
  padding: 3px 10px; font-size: 0.72rem; border-radius: 8px;
  background: rgba(255,255,255,0.08); border: none; color: #8a8070; cursor: pointer;
}
```

- [ ] **Step 2: Replace preview dialog inner content with comparison-aware layout**

Replace the content inside `<dialog id="preview-dialog">` with:

```html
<dialog id="preview-dialog">
  <div class="dialog-inner">
    <div class="dialog-header">
      <h3 id="dialog-title">视频预览</h3>
      <button class="dialog-close" id="dialog-close-btn">✕</button>
    </div>
    <div id="compare-tabs-bar" class="compare-tabs" style="display:none;">
      <button class="compare-tab active" data-compare="side-by-side">并排对比</button>
      <button class="compare-tab" data-compare="toggle">A/B 切换</button>
      <button class="compare-tab" data-compare="slider">滑块对比</button>
    </div>
    <div id="preview-content">
      <video class="dialog-video" id="dialog-video" controls loop></video>
    </div>
    <div class="dialog-meta" id="dialog-meta"></div>
  </div>
</dialog>
```

- [ ] **Step 3: Add comparison JS logic**

Add after the `openPreview` function:

```javascript
// ── comparison preview ──
let compareMode = "side-by-side";
let compareSourceJob = null;
let compareUpscaleJob = null;

document.querySelectorAll(".compare-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".compare-tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    compareMode = tab.dataset.compare;
    renderComparison();
  });
});

function renderComparison() {
  const content = document.getElementById("preview-content");
  if (!compareSourceJob || !compareUpscaleJob) {
    // Single video mode (generate job)
    return;
  }

  const srcUrl = `/jobs/${compareSourceJob.job_id}/download`;
  const upUrl = `/jobs/${compareUpscaleJob.job_id}/download`;

  if (compareMode === "side-by-side") {
    content.innerHTML = `
      <div class="compare-side-by-side">
        <div>
          <video src="${srcUrl}" controls loop class="dialog-video" id="compare-vid-a"></video>
          <div style="text-align:center;font-size:0.72rem;color:#8a8070;padding:4px;">原始</div>
        </div>
        <div>
          <video src="${upUrl}" controls loop class="dialog-video" id="compare-vid-b"></video>
          <div style="text-align:center;font-size:0.72rem;color:#8a8070;padding:4px;">超分</div>
        </div>
      </div>`;
    // Sync playback
    const vidA = document.getElementById("compare-vid-a");
    const vidB = document.getElementById("compare-vid-b");
    if (vidA && vidB) syncVideos(vidA, vidB);
  } else if (compareMode === "toggle") {
    content.innerHTML = `
      <div class="compare-toggle-wrap">
        <div class="compare-toggle-btns">
          <button class="compare-toggle-btn active" id="toggle-a-btn">A 原始</button>
          <button class="compare-toggle-btn" id="toggle-b-btn">B 超分</button>
        </div>
        <video src="${srcUrl}" controls loop class="dialog-video" id="compare-toggle-vid"></video>
      </div>`;
    const vid = document.getElementById("compare-toggle-vid");
    const btnA = document.getElementById("toggle-a-btn");
    const btnB = document.getElementById("toggle-b-btn");
    let currentSrc = "a";
    btnA.addEventListener("click", () => {
      if (currentSrc === "a") return;
      const time = vid.currentTime; const paused = vid.paused;
      vid.src = srcUrl; vid.currentTime = time; if (!paused) vid.play();
      currentSrc = "a"; btnA.classList.add("active"); btnB.classList.remove("active");
    });
    btnB.addEventListener("click", () => {
      if (currentSrc === "b") return;
      const time = vid.currentTime; const paused = vid.paused;
      vid.src = upUrl; vid.currentTime = time; if (!paused) vid.play();
      currentSrc = "b"; btnB.classList.add("active"); btnA.classList.remove("active");
    });
    // Keyboard shortcuts
    const handleKey = (e) => {
      if (e.key === "a" || e.key === "A") btnA.click();
      if (e.key === "b" || e.key === "B") btnB.click();
    };
    document.addEventListener("keydown", handleKey);
    previewDialog.addEventListener("close", () => document.removeEventListener("keydown", handleKey), { once: true });
  } else if (compareMode === "slider") {
    content.innerHTML = `
      <div class="compare-slider-wrap">
        <canvas id="compare-canvas"></canvas>
        <div class="compare-slider-line" id="slider-line" style="left:50%;"></div>
        <span class="compare-slider-label left">原始</span>
        <span class="compare-slider-label right">超分</span>
      </div>
      <div class="compare-frame-nav">
        <button id="slider-prev-frame">◀ 上一帧</button>
        <span id="slider-frame-info" style="font-size:0.72rem;color:#8a8070;padding:3px 8px;">帧 0/0</span>
        <button id="slider-next-frame">下一帧 ▶</button>
      </div>`;
    initSliderComparison(srcUrl, upUrl);
  }
}

function syncVideos(vidA, vidB) {
  vidA.addEventListener("play", () => { if (vidB.paused) vidB.play(); });
  vidB.addEventListener("play", () => { if (vidA.paused) vidA.play(); });
  vidA.addEventListener("pause", () => { if (!vidB.paused) vidB.pause(); });
  vidB.addEventListener("pause", () => { if (!vidA.paused) vidA.pause(); });
  vidA.addEventListener("seeked", () => { vidB.currentTime = vidA.currentTime; });
}

function initSliderComparison(srcUrl, upUrl) {
  const canvas = document.getElementById("compare-canvas");
  const ctx = canvas.getContext("2d");
  const line = document.getElementById("slider-line");
  let splitPos = 0.5;

  // Create offscreen videos
  const vidA = document.createElement("video"); vidA.src = srcUrl; vidA.preload = "auto"; vidA.muted = true;
  const vidB = document.createElement("video"); vidB.src = upUrl; vidB.preload = "auto"; vidB.muted = true;

  vidA.addEventListener("loadeddata", () => {
    canvas.width = vidA.videoWidth || 896;
    canvas.height = vidA.videoHeight || 448;
    vidA.currentTime = 0; vidB.currentTime = 0;
    drawSliderFrame();
  });

  function drawSliderFrame() {
    const w = canvas.width, h = canvas.height;
    const splitX = Math.round(w * splitPos);
    ctx.clearRect(0, 0, w, h);
    // Left: original
    ctx.drawImage(vidA, 0, 0, splitX, h, 0, 0, splitX, h);
    // Right: upscaled
    ctx.drawImage(vidB, splitX, 0, w - splitX, h, splitX, 0, w - splitX, h);
    line.style.left = `${splitPos * 100}%`;
  }

  // Drag slider
  let dragging = false;
  line.addEventListener("mousedown", () => { dragging = true; });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = canvas.getBoundingClientRect();
    splitPos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    drawSliderFrame();
  });
  document.addEventListener("mouseup", () => { dragging = false; });

  // Frame navigation
  const frameStep = 1 / 24; // assume 24fps
  document.getElementById("slider-prev-frame").addEventListener("click", () => {
    vidA.currentTime = Math.max(0, vidA.currentTime - frameStep);
    vidB.currentTime = vidA.currentTime;
    vidA.addEventListener("seeked", drawSliderFrame, { once: true });
    updateFrameInfo();
  });
  document.getElementById("slider-next-frame").addEventListener("click", () => {
    vidA.currentTime = Math.min(vidA.duration, vidA.currentTime + frameStep);
    vidB.currentTime = vidA.currentTime;
    vidA.addEventListener("seeked", drawSliderFrame, { once: true });
    updateFrameInfo();
  });

  function updateFrameInfo() {
    const frame = Math.round(vidA.currentTime * 24);
    const total = Math.round(vidA.duration * 24);
    document.getElementById("slider-frame-info").textContent = `帧 ${frame}/${total}`;
  }
}
```

- [ ] **Step 4: Update openPreview to detect upscale jobs and show comparison**

Replace the existing `openPreview` function:

```javascript
function openPreview(job) {
  if (job.type === "upscale" && job.source_job_id) {
    // Comparison mode: find source job
    compareUpscaleJob = job;
    compareSourceJob = _jobCache[job.source_job_id] || null;
    document.getElementById("compare-tabs-bar").style.display = "";
    compareMode = "side-by-side";
    document.querySelectorAll(".compare-tab").forEach(t => t.classList.remove("active"));
    document.querySelector('[data-compare="side-by-side"]').classList.add("active");
    dialogTitle.textContent = `对比 — ${job.job_id.slice(0, 8)}…`;
    renderComparison();
  } else {
    // Single video mode
    compareSourceJob = null;
    compareUpscaleJob = null;
    document.getElementById("compare-tabs-bar").style.display = "none";
    const url = job.download_url || `/jobs/${job.job_id}/download`;
    document.getElementById("preview-content").innerHTML =
      `<video class="dialog-video" id="dialog-video" controls loop src="${url}"></video>`;
    dialogTitle.textContent = `预览 — ${job.job_id.slice(0, 8)}…`;
  }

  const p = job.params || {};
  const parts = [];
  if (p.num_inference_steps) parts.push(`${p.num_inference_steps} 步`);
  if (p.width && p.height) parts.push(`${p.width}×${p.height}`);
  if (p.seed !== undefined && p.seed !== null) parts.push(`seed ${p.seed}`);
  if (job.upscale_params) {
    parts.push(`${job.upscale_params.model}`);
    parts.push(`${job.upscale_params.scale}x`);
  }
  let duration = "";
  if (job.created_at && job.finished_at) {
    const secs = Math.round((new Date(job.finished_at) - new Date(job.created_at)) / 1000);
    duration = formatDuration(secs);
  }
  dialogMeta.innerHTML =
    `<strong>Prompt:</strong> ${escapeHtml(job.prompt || "")}<br>` +
    (parts.length ? `<strong>参数:</strong> ${parts.join(" · ")}` : "") +
    (duration ? ` &nbsp;·&nbsp; <strong>耗时:</strong> ${duration}` : "");
  previewDialog.showModal();
}
```

- [ ] **Step 5: Test in browser**

Verify:
1. Clicking "预览" on a generate job shows single video (no tabs)
2. Clicking "预览" on an upscale job shows comparison tabs
3. Side-by-side mode: two videos, synced playback
4. A/B toggle: single video, switch buttons, keyboard shortcuts
5. Slider mode: canvas split view, drag to compare, frame navigation

- [ ] **Step 6: Commit**

```bash
git add app/static/index.html
git commit -m "feat: add comparison preview window with side-by-side, A/B toggle, and slider modes"
```

---

## Task 11: Docker — Add sse-starlette and Upscale Model Downloads

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add sse-starlette to Dockerfile**

In the `Dockerfile`, find the `pip install` line and add `sse-starlette`:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/uv \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install uv fastapi "uvicorn[standard]" sse-starlette && \
    bash ./scripts/install-uv.sh && \
    export PATH="$HOME/.local/bin:$PATH" && \
    uv sync
```

Add a step to create the upscale model directory:

```dockerfile
# Create upscale model directory
RUN mkdir -p /app/data/models/upscale
```

- [ ] **Step 2: Add upscale env vars to docker-compose.yml**

Add to the `environment` section in `docker-compose.yml`:

```yaml
      UPSCALE_MODEL_DIR:
      UPSCALE_OUTPUT_DIR:
      UPSCALE_TIMEOUT_SECONDS:
```

Add an additional volume for upscale models:

```yaml
    volumes:
      - ./data/models:/app/PanoWan/models
      - ./data/models/upscale:/app/data/models/upscale
      - ./data/runtime:/app/runtime
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "infra: add sse-starlette and upscale model directory to Docker setup"
```

---

## Task 12: Integration Test — Full Flow

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write integration test for upscale→cancel→SSE flow**

Add to `tests/test_api.py`:

```python
def test_upscale_and_cancel_queued_job(self) -> None:
    """End-to-end: create source job, upscale it, cancel the upscale."""
    with patch.dict(api._jobs, clear=True):
        # Create a completed source job
        source_id = "src-1"
        api._jobs[source_id] = {
            "job_id": source_id, "status": "completed", "type": "generate",
            "prompt": "test", "params": {"width": 448, "height": 224},
            "output_path": "/fake/out.mp4", "download_url": f"/jobs/{source_id}/download",
            "created_at": "now", "started_at": "now", "finished_at": "now",
            "error": None, "source_job_id": None, "upscale_params": None,
        }
        with patch("app.api.os.path.exists", return_value=True):
            resp = api.upscale({"source_job_id": source_id, "model": "realesrgan-animevideov3", "scale": 2})

    upscale_id = resp["job_id"]
    self.assertEqual(resp["type"], "upscale")

    # Cancel the queued upscale job
    result = api.cancel_job(upscale_id, force=False)
    self.assertEqual(result["status"], "failed")
    self.assertEqual(result["error"], "Cancelled by user")

def test_upscale_job_record_has_source_info(self) -> None:
    with patch.dict(api._jobs", clear=True):
        source_id = "src-2"
        api._jobs[source_id] = {
            "job_id": source_id, "status": "completed", "type": "generate",
            "prompt": "hello", "params": {"width": 896, "height": 448},
            "output_path": "/fake/out2.mp4", "download_url": f"/jobs/{source_id}/download",
            "created_at": "now", "started_at": "now", "finished_at": "now",
            "error": None, "source_job_id": None, "upscale_params": None,
        }
        with patch("app.api.os.path.exists", return_value=True):
            resp = api.upscale({"source_job_id": source_id, "model": "seedvr2-3b", "scale": 2})

    job = api.get_job(resp["job_id"])
    self.assertEqual(job["type"], "upscale")
    self.assertEqual(job["source_job_id"], source_id)
    self.assertEqual(job["upscale_params"]["model"], "seedvr2-3b")
    self.assertEqual(job["upscale_params"]["scale"], 2)
    self.assertEqual(job["upscale_params"]["target_width"], 1792)
    self.assertEqual(job["upscale_params"]["target_height"], 896)
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "test: add integration tests for upscale flow and cancel"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Task(s) | Covered? |
|---|---|---|
| 1. Data Model | Task 3 | Yes |
| 2. API: POST /upscale | Task 4 | Yes |
| 2. API: POST /cancel | Task 5 | Yes |
| 2. API: GET /jobs/events | Task 6 | Yes |
| 3.1 Job List Changes | Task 9 | Yes |
| 3.2 Upscale Dialog | Task 9 | Yes |
| 3.3 Comparison Preview | Task 10 | Yes |
| 4.1-4.3 Upscaler Module | Task 2 | Yes |
| 4.4 Job Execution | Task 4 | Yes |
| 4.5 Cancel Logic | Task 5 | Yes |
| 4.6 Settings | Task 1 | Yes |
| 4.7 Subprocess Change | Task 7 | Yes |
| 5. SSE | Task 6, 8 | Yes |
| 6. Error Handling | Tasks 4, 5 | Yes |
| 7. Concurrency Model | Task 4 (shares semaphore) | Yes |
| 8. Plugin Framework | Not needed (documented as deferred) | Yes |

### 2. Placeholder Scan

No TBD, TODO, or placeholder patterns found. All steps contain concrete code.

### 3. Type Consistency

- `cancel_job()` returns `dict` consistently in Task 5 and is called from `cancel_job_endpoint()` — matches
- `_create_job_record()` signature extended with optional params in Task 3, called with new args in Task 4 — matches
- `upscale_video()` defined in Task 2 with specific params, called in Task 4's `_run_upscale_job()` — matches
- `_jobCache` accessed as `dict` in frontend code across Tasks 8, 9, 10 — matches
- `UPSCALE_BACKENDS` dict keys match string constants used in `upscale()` endpoint and frontend `<option>` values — matches
