# Docker Compose Product Runtime Rearchitecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Docker, Compose, scripts, and Python service boundaries so PanoWan Worker runs as a product runtime with CPU-only API, GPU worker, and explicit model setup roles.

**Architecture:** Introduce a local filesystem job backend as the API/Worker contract, then move generation and upscale execution behind engine adapters owned by the worker. Dockerfile targets and Compose services will mirror those product roles: `api`, `worker-panowan`, and `model-setup`, with dev overrides that preserve reload and bind-mount convenience without defining production topology.

**Tech Stack:** Python 3.13, FastAPI, sse-starlette, uvicorn, uv, Docker multi-stage builds, Docker Compose, bash scripts, unittest.

---

## File Structure

- Create: `pyproject.toml` — root product runtime dependencies and dev test tooling.
- Create: `app/paths.py` — POSIX runtime path helpers for container paths, avoiding Windows host `os.path.join` leakage.
- Modify: `app/settings.py` — product runtime settings, engine directory, model root, and POSIX container path semantics.
- Create: `app/jobs/__init__.py` — public exports for job backend types.
- Create: `app/jobs/local.py` — local filesystem job backend shared by API and worker.
- Create: `app/engines/__init__.py` — engine package exports.
- Create: `app/engines/base.py` — engine adapter protocol and job execution result type.
- Create: `app/engines/registry.py` — explicit engine registry.
- Create: `app/engines/panowan.py` — PanoWan adapter wrapping current generation and upscale execution.
- Modify: `app/generator.py` — make generation use configured engine directory and absolute model paths without owning API job lifecycle.
- Modify: `app/upscaler.py` — keep execution callable by worker adapter; do not import from API startup path unless needed for request validation.
- Modify: `app/api.py` — keep FastAPI routes and SSE, remove in-process GPU execution/background generation, write queued jobs to backend.
- Create: `app/api_service.py` — API role entrypoint with dev reload support.
- Create: `app/worker_service.py` — worker role entrypoint and polling loop.
- Modify: `app/main.py` — replace legacy all-in-one entrypoint with API compatibility shim or remove Docker usage from it.
- Create: `scripts/start-api.sh` — API-only startup script.
- Create: `scripts/start-worker.sh` — worker-only startup script.
- Create: `scripts/model-setup.sh` — one-shot asset preparation script.
- Create: `scripts/check-runtime.sh` — fast worker runtime validation script.
- Modify: `scripts/lib/env.sh` — product role environment defaults for host, API, worker, and model setup.
- Modify: `scripts/download-models.sh` — keep host-side model setup aligned with `/models` container layout and `MODEL_ROOT` semantics.
- Modify: `Dockerfile` — replace `prod`/`dev` all-in-one targets with role-oriented targets.
- Delete: `docker-compose.yml` old all-in-one content by replacing it with split service topology.
- Delete: `docker-compose-dev.yml` old all-in-one dev content by replacing it with role override topology.
- Modify: `Makefile` — replace `DEV=1` switching with explicit production/dev/setup commands.
- Modify: `.env.example` — rewrite around product runtime variables.
- Modify: `.dockerignore` — keep model/output exclusions and add root build artifacts if introduced.
- Modify: `README.md` — update quick start from all-in-one to setup/API/worker topology.
- Modify: `docs/architecture/product-runtime.md` — mark implementation status after changes are complete.
- Modify: `docs/architecture/adr/0001-engine-oriented-product-runtime.md` — add implementation note if any command names differ from the ADR guidance.
- Modify/Create tests under `tests/` — cover settings path semantics, local job backend, API no-engine-startup behavior, engine registry, worker job execution, and Compose/Docker text invariants.

---

## Task 1: Add Root Product Runtime Project Metadata

**Files:**
- Create: `pyproject.toml`
- Modify: `.dockerignore`
- Test: command-only validation

- [ ] **Step 1: Create root `pyproject.toml`**

Create a root product runtime manifest. Do not add PanoWan engine dependencies here.

```toml
[project]
name = "panowan-worker"
version = "0.1.0"
description = "Engine-oriented video generation product runtime"
requires-python = ">=3.13,<3.14"
dependencies = [
    "fastapi>=0.115.0",
    "sse-starlette>=2.1.0",
    "uvicorn[standard]>=0.30.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.8.0",
]

[tool.ruff]
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

- [ ] **Step 2: Update `.dockerignore` for root Python artifacts**

Ensure these entries exist while keeping existing model/output exclusions:

```text
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
*.pyc
```

- [ ] **Step 3: Validate root dependency resolution**

Run:

```bash
rtk uv lock
```

Expected: `uv.lock` is created or updated at repository root, and it does not include `torch`, `xformers`, or `flash-attn` as root project dependencies.

- [ ] **Step 4: Verify root test command still starts**

Run on Windows host:

```bash
rtk test python -m unittest discover -s tests
```

Expected before later tasks: existing tests may still fail due known Windows path/mock issues, but Python must run and discover tests. Do not fix unrelated failures in this task.

- [ ] **Step 5: Commit**

```bash
rtk git add pyproject.toml uv.lock .dockerignore
rtk git commit -m "build: add product runtime python project"
```

---

## Task 2: Normalize Runtime Path Semantics

**Files:**
- Create: `app/paths.py`
- Modify: `app/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Add failing tests for POSIX container paths on Windows host**

Add these tests to `tests/test_settings.py`:

```python
def test_container_path_join_uses_posix_separators(self):
    from app.paths import container_join

    self.assertEqual(
        container_join("/engines/panowan", "models/PanoWan/latest-lora.ckpt"),
        "/engines/panowan/models/PanoWan/latest-lora.ckpt",
    )


def test_load_settings_uses_model_root_and_engine_dir(self):
    env = {
        "PANOWAN_ENGINE_DIR": "/engines/panowan",
        "MODEL_ROOT": "/models",
        "WAN_MODEL_PATH": "/models/Wan-AI/Wan2.1-T2V-1.3B",
        "LORA_CHECKPOINT_PATH": "/models/PanoWan/latest-lora.ckpt",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        loaded = load_settings()

    self.assertEqual(loaded.panowan_engine_dir, "/engines/panowan")
    self.assertEqual(loaded.model_root, "/models")
    self.assertEqual(
        loaded.wan_diffusion_absolute_path,
        "/models/Wan-AI/Wan2.1-T2V-1.3B/diffusion_pytorch_model.safetensors",
    )
    self.assertEqual(
        loaded.lora_absolute_path,
        "/models/PanoWan/latest-lora.ckpt",
    )
```

Ensure imports at the top include:

```python
import os
from unittest import mock
```

- [ ] **Step 2: Run settings tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_settings -v
```

Expected: FAIL because `app.paths` does not exist and `Settings` does not expose `model_root` / `panowan_engine_dir` yet.

- [ ] **Step 3: Create `app/paths.py`**

```python
import posixpath


def container_join(base: str, *parts: str) -> str:
    cleaned_parts = [part.strip("/") for part in parts if part]
    if not cleaned_parts:
        return base
    return posixpath.join(base.rstrip("/"), *cleaned_parts)


def container_child(path: str, child: str) -> str:
    return container_join(path, child)
```

- [ ] **Step 4: Update `app/settings.py` fields and path properties**

Change the dataclass fields from `panowan_app_dir` to the product role names while preserving a compatibility property for code that has not yet moved in later tasks:

```python
from dataclasses import dataclass

from .paths import container_child, container_join


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
    default_prompt: str
    generation_timeout_seconds: int
    default_num_inference_steps: int
    default_width: int
    default_height: int
    upscale_model_dir: str
    upscale_output_dir: str
    upscale_timeout_seconds: int
    max_concurrent_jobs: int
    host: str
    port: int
    worker_poll_interval_seconds: float

    @property
    def panowan_app_dir(self) -> str:
        return self.panowan_engine_dir

    @property
    def wan_model_absolute_path(self) -> str:
        return self.wan_model_path

    @property
    def wan_diffusion_absolute_path(self) -> str:
        return container_child(self.wan_model_absolute_path, "diffusion_pytorch_model.safetensors")

    @property
    def wan_t5_absolute_path(self) -> str:
        return container_child(self.wan_model_absolute_path, "models_t5_umt5-xxl-enc-bf16.pth")

    @property
    def lora_absolute_path(self) -> str:
        return self.lora_checkpoint_path
```

Update `load_settings()` to use product defaults:

```python
def load_settings() -> Settings:
    runtime_dir = os.getenv("RUNTIME_DIR", "/app/runtime")
    model_root = os.getenv("MODEL_ROOT", "/models")
    output_dir = os.getenv("OUTPUT_DIR", container_child(runtime_dir, "outputs"))
    return Settings(
        service_title="PanoWan Worker",
        service_version="1.0.0",
        panowan_engine_dir=os.getenv("PANOWAN_ENGINE_DIR", "/engines/panowan"),
        model_root=model_root,
        wan_model_path=os.getenv(
            "WAN_MODEL_PATH",
            container_join(model_root, "Wan-AI/Wan2.1-T2V-1.3B"),
        ),
        lora_checkpoint_path=os.getenv(
            "LORA_CHECKPOINT_PATH",
            container_join(model_root, "PanoWan/latest-lora.ckpt"),
        ),
        runtime_dir=runtime_dir,
        output_dir=output_dir,
        job_store_path=os.getenv("JOB_STORE_PATH", container_child(runtime_dir, "jobs.json")),
        default_prompt=os.getenv("DEFAULT_PROMPT", "A beautiful mountain landscape at sunset"),
        generation_timeout_seconds=int(os.getenv("GENERATION_TIMEOUT_SECONDS", "1800")),
        default_num_inference_steps=int(os.getenv("DEFAULT_NUM_INFERENCE_STEPS", "50")),
        default_width=int(os.getenv("DEFAULT_WIDTH", "896")),
        default_height=int(os.getenv("DEFAULT_HEIGHT", "448")),
        upscale_model_dir=os.getenv("UPSCALE_MODEL_DIR", container_child(model_root, "upscale")),
        upscale_output_dir=os.getenv("UPSCALE_OUTPUT_DIR", output_dir),
        upscale_timeout_seconds=int(os.getenv("UPSCALE_TIMEOUT_SECONDS", "1800")),
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "1")),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        worker_poll_interval_seconds=float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2")),
    )
```

- [ ] **Step 5: Run settings tests**

Run:

```bash
rtk test python -m unittest tests.test_settings -v
```

Expected: PASS for settings tests.

- [ ] **Step 6: Commit**

```bash
rtk git add app/paths.py app/settings.py tests/test_settings.py
rtk git commit -m "fix: use container path semantics for runtime settings"
```

---

## Task 3: Extract Local Job Backend Boundary

**Files:**
- Create: `app/jobs/__init__.py`
- Create: `app/jobs/local.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write failing local job backend tests**

Create `tests/test_jobs.py`:

```python
import tempfile
import unittest

from app.jobs.local import LocalJobBackend


class LocalJobBackendTests(unittest.TestCase):
    def test_create_update_and_list_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            created = backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "prompt": "mountain",
                    "params": {"width": 896, "height": 448},
                    "output_path": f"{tmp}/outputs/output_job-1.mp4",
                }
            )
            self.assertEqual(created["status"], "queued")

            updated = backend.update_job("job-1", status="running", started_at="now")
            self.assertEqual(updated["status"], "running")
            self.assertEqual(updated["started_at"], "now")

            listed = backend.list_jobs()
            self.assertEqual([job["job_id"] for job in listed], ["job-1"])

    def test_claim_next_job_marks_it_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job({"job_id": "job-1", "status": "queued", "type": "generate"})

            claimed = backend.claim_next_job(worker_id="worker-a")

            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["job_id"], "job-1")
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(claimed["worker_id"], "worker-a")
            self.assertIsNone(backend.claim_next_job(worker_id="worker-a"))

    def test_restore_marks_incomplete_jobs_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/jobs.json"
            backend = LocalJobBackend(path)
            backend.create_job({"job_id": "job-1", "status": "running", "type": "generate"})

            restored = LocalJobBackend(path)
            job = restored.get_job("job-1")

            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Service restarted before the job completed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run job backend tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_jobs -v
```

Expected: FAIL because `app.jobs.local` does not exist.

- [ ] **Step 3: Create `app/jobs/local.py`**

```python
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalJobBackend:
    def __init__(self, job_store_path: str):
        self.job_store_path = job_store_path
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self.restore()

    def restore(self) -> None:
        if not os.path.exists(self.job_store_path):
            return
        with open(self.job_store_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_jobs = payload.get("jobs", payload)
        if not isinstance(raw_jobs, dict):
            raise ValueError("Job store payload must contain a jobs object")
        with self._lock:
            self._jobs = {
                str(job_id): self._normalize_job_record(str(job_id), record)
                for job_id, record in raw_jobs.items()
                if isinstance(record, dict)
            }
            self._persist_unlocked()

    def create_job(self, record: dict[str, Any]) -> dict[str, Any]:
        job_id = str(record["job_id"])
        normalized = self._normalize_job_record(job_id, record, restore=False)
        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"Job {job_id} already exists")
            self._jobs[job_id] = normalized
            self._persist_unlocked()
            return dict(normalized)

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            self._jobs[job_id].update(updates)
            self._persist_unlocked()
            return dict(self._jobs[job_id])

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values()]
        jobs.sort(key=lambda job: job.get("created_at") or "", reverse=True)
        return jobs

    def claim_next_job(self, worker_id: str) -> dict[str, Any] | None:
        with self._lock:
            queued = sorted(
                (job for job in self._jobs.values() if job.get("status") == "queued"),
                key=lambda job: job.get("created_at") or "",
            )
            if not queued:
                return None
            job = queued[0]
            job["status"] = "running"
            job["started_at"] = now_iso()
            job["worker_id"] = worker_id
            self._persist_unlocked()
            return dict(job)

    def fail_job(self, job_id: str, error: str) -> dict[str, Any]:
        return self.update_job(job_id, status="failed", finished_at=now_iso(), error=error)

    def complete_job(self, job_id: str, output_path: str) -> dict[str, Any]:
        return self.update_job(
            job_id,
            status="completed",
            finished_at=now_iso(),
            output_path=output_path,
        )

    def _normalize_job_record(
        self, job_id: str, record: dict[str, Any], restore: bool = True
    ) -> dict[str, Any]:
        normalized = dict(record)
        normalized["job_id"] = str(normalized.get("job_id") or job_id)
        normalized.setdefault("download_url", f"/jobs/{normalized['job_id']}/download")
        normalized.setdefault("prompt", "")
        normalized.setdefault("params", {})
        normalized.setdefault("output_path", "")
        normalized.setdefault("created_at", now_iso())
        normalized.setdefault("started_at", None)
        normalized.setdefault("finished_at", None)
        normalized.setdefault("error", None)
        normalized.setdefault("status", "queued")
        normalized.setdefault("type", "generate")
        normalized.setdefault("source_job_id", None)
        normalized.setdefault("upscale_params", None)
        normalized.setdefault("worker_id", None)
        if restore and normalized["status"] in {"queued", "running"}:
            normalized["status"] = "failed"
            normalized["finished_at"] = normalized["finished_at"] or now_iso()
            normalized["error"] = "Service restarted before the job completed"
        return normalized

    def _persist_unlocked(self) -> None:
        os.makedirs(os.path.dirname(self.job_store_path), exist_ok=True)
        temp_path = f"{self.job_store_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"jobs": self._jobs}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, self.job_store_path)
```

- [ ] **Step 4: Create `app/jobs/__init__.py`**

```python
from .local import LocalJobBackend, now_iso

__all__ = ["LocalJobBackend", "now_iso"]
```

- [ ] **Step 5: Run job backend tests**

Run:

```bash
rtk test python -m unittest tests.test_jobs -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add app/jobs tests/test_jobs.py
rtk git commit -m "feat: add local job backend boundary"
```

---

## Task 4: Add Engine Adapter Boundary

**Files:**
- Create: `app/engines/__init__.py`
- Create: `app/engines/base.py`
- Create: `app/engines/registry.py`
- Create: `app/engines/panowan.py`
- Modify: `app/generator.py`
- Test: `tests/test_engines.py`

- [ ] **Step 1: Write failing engine registry tests**

Create `tests/test_engines.py`:

```python
import unittest
from unittest import mock

from app.engines.base import EngineResult
from app.engines.panowan import PanoWanEngine
from app.engines.registry import EngineRegistry


class EngineRegistryTests(unittest.TestCase):
    def test_register_and_get_engine(self):
        engine = PanoWanEngine()
        registry = EngineRegistry()
        registry.register(engine)

        self.assertIs(registry.get("panowan"), engine)
        self.assertIn("t2v", registry.get("panowan").capabilities)

    def test_unknown_engine_raises_key_error(self):
        registry = EngineRegistry()
        with self.assertRaises(KeyError):
            registry.get("missing")


class PanoWanEngineTests(unittest.TestCase):
    @mock.patch("app.engines.panowan.generate_video")
    def test_run_generate_delegates_to_generator(self, generate_video):
        generate_video.return_value = {"output_path": "/app/runtime/outputs/output_job-1.mp4"}
        engine = PanoWanEngine()

        result = engine.run({"job_id": "job-1", "type": "generate", "prompt": "sky"})

        self.assertEqual(
            result,
            EngineResult(output_path="/app/runtime/outputs/output_job-1.mp4", metadata={}),
        )
        generate_video.assert_called_once()
```

- [ ] **Step 2: Run engine tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_engines -v
```

Expected: FAIL because engine modules do not exist.

- [ ] **Step 3: Create `app/engines/base.py`**

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EngineResult:
    output_path: str
    metadata: dict


class EngineAdapter(Protocol):
    name: str
    capabilities: tuple[str, ...]

    def validate_runtime(self) -> None:
        ...

    def run(self, job: dict) -> EngineResult:
        ...
```

- [ ] **Step 4: Create `app/engines/registry.py`**

```python
from .base import EngineAdapter


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, EngineAdapter] = {}

    def register(self, engine: EngineAdapter) -> None:
        self._engines[engine.name] = engine

    def get(self, name: str) -> EngineAdapter:
        if name not in self._engines:
            raise KeyError(f"Unknown engine: {name}")
        return self._engines[name]
```

- [ ] **Step 5: Create `app/engines/panowan.py`**

```python
import os

from app.generator import generate_video
from app.settings import settings
from app.upscaler import upscale_video

from .base import EngineResult


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v", "upscale")

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
                "PanoWan runtime assets are missing. Run `make setup-models` first:\n"
                f"{joined}"
            )

    def run(self, job: dict) -> EngineResult:
        job_type = job.get("type", "generate")
        if job_type == "upscale":
            params = job.get("upscale_params") or {}
            result = upscale_video(
                input_path=job["source_output_path"],
                output_path=job["output_path"],
                model=params["model"],
                scale=params["scale"],
                target_width=params.get("target_width"),
                target_height=params.get("target_height"),
                model_dir=settings.upscale_model_dir,
                timeout_seconds=settings.upscale_timeout_seconds,
            )
            return EngineResult(output_path=result["output_path"], metadata={})

        result = generate_video(job)
        return EngineResult(output_path=result["output_path"], metadata={})
```

- [ ] **Step 6: Create `app/engines/__init__.py`**

```python
from .base import EngineAdapter, EngineResult
from .panowan import PanoWanEngine
from .registry import EngineRegistry

__all__ = ["EngineAdapter", "EngineResult", "EngineRegistry", "PanoWanEngine"]
```

- [ ] **Step 7: Update `app/generator.py` to use `settings.panowan_engine_dir` and absolute model paths**

In `generate_video`, change the command args and working directory:

```python
cmd = [
    "uv",
    "run",
    "panowan-test",
    "--wan-model-path",
    settings.wan_model_path,
    "--lora-checkpoint-path",
    settings.lora_checkpoint_path,
    "--output-path",
    output_path,
    "--prompt",
    prompt,
    "--num-inference-steps",
    str(params["num_inference_steps"]),
    "--width",
    str(params["width"]),
    "--height",
    str(params["height"]),
    "--seed",
    str(params["seed"]),
]
```

Ensure `subprocess.Popen(..., cwd=settings.panowan_engine_dir, ...)` is used.

- [ ] **Step 8: Run engine and generator tests**

Run:

```bash
rtk test python -m unittest tests.test_engines tests.test_generator -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
rtk git add app/engines app/generator.py tests/test_engines.py
rtk git commit -m "feat: add panowan engine adapter boundary"
```

---

## Task 5: Convert API to Job Submission Only

**Files:**
- Modify: `app/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Update API tests to assert no in-process execution**

In `tests/test_api.py`, replace tests that execute `background_tasks.tasks[0]` with backend state assertions. Add this test:

```python
def test_generate_creates_queued_job_without_running_engine(self):
    with tempfile.TemporaryDirectory() as tmp:
        with mock.patch.dict(
            os.environ,
            {
                "RUNTIME_DIR": tmp,
                "JOB_STORE_PATH": f"{tmp}/jobs.json",
                "OUTPUT_DIR": f"{tmp}/outputs",
            },
            clear=True,
        ):
            from app.jobs.local import LocalJobBackend
            from app.settings import load_settings

            loaded = load_settings()
            backend = LocalJobBackend(loaded.job_store_path)
            record = backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "prompt": "sky",
                    "params": {"width": 896, "height": 448},
                    "output_path": f"{tmp}/outputs/output_job-1.mp4",
                }
            )

            self.assertEqual(record["status"], "queued")
```

Also add an API-level test with `TestClient` after the module reload pattern already used in the file:

```python
def test_generate_endpoint_only_queues_job(self):
    response = self.client.post("/generate", json={"prompt": "sky"})

    self.assertEqual(response.status_code, 202)
    payload = response.json()
    self.assertEqual(payload["status"], "queued")
    job = self.client.get(f"/jobs/{payload['job_id']}").json()
    self.assertEqual(job["status"], "queued")
```

- [ ] **Step 2: Run API tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_api -v
```

Expected: FAIL because current API still schedules in-process background tasks and owns execution helpers.

- [ ] **Step 3: Refactor `app/api.py` imports**

Remove imports that make API startup own execution:

```python
import subprocess
import threading
import traceback
from fastapi import BackgroundTasks
from .generator import generate_video, log_startup_diagnostics
```

Keep request parsing helpers only if they remain lightweight:

```python
from .generator import extract_prompt, resolve_inference_params
from .jobs import LocalJobBackend, now_iso
from .settings import settings
from .sse import broadcast_job_event, subscribe, unsubscribe
```

Do not import `app.engines`, `torch`, PanoWan, or worker modules in `app/api.py`.

- [ ] **Step 4: Replace global in-memory job state with backend accessor**

Add:

```python
def get_job_backend() -> LocalJobBackend:
    return LocalJobBackend(settings.job_store_path)
```

Update `_create_job_record`, `_update_job`, `_get_job`, and `list_jobs` to call `get_job_backend()` rather than `_jobs` / `_jobs_lock`.

- [ ] **Step 5: Remove `_run_generation_job` and `_run_upscale_job` from API**

Delete `_gpu_slot`, `_is_job_cancelled`, `_run_generation_job`, and `_run_upscale_job`. The worker will claim queued jobs instead.

- [ ] **Step 6: Update `/generate` route signature and body**

Change:

```python
@app.post("/generate", status_code=202)
def generate(payload: dict) -> dict:
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    job_payload = dict(payload)
    job_payload["id"] = job_id
    params = resolve_inference_params(job_payload)
    record = _create_job_record(job_id, prompt, output_path, params, payload=job_payload)
    return {
        "job_id": job_id,
        "status": record["status"],
        "prompt": prompt,
        "output_path": output_path,
        "download_url": record["download_url"],
    }
```

Update `_create_job_record` to include `payload` in the stored record:

```python
"payload": payload or {},
```

- [ ] **Step 7: Update `/upscale` route to store worker-ready payload**

When creating an upscale job, include:

```python
payload={
    "source_job_id": source_job_id,
    "source_output_path": source_job["output_path"],
    "output_path": output_path,
    "upscale_params": upscale_params,
}
```

Also store top-level `source_output_path` so the worker adapter can run without re-querying API state.

- [ ] **Step 8: Simplify startup handler**

Change startup to initialize and restore the backend only:

```python
@app.on_event("startup")
def on_startup() -> None:
    try:
        get_job_backend().restore()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WARNING: could not restore jobs from disk: {exc}", flush=True)
```

- [ ] **Step 9: Run API tests**

Run:

```bash
rtk test python -m unittest tests.test_api -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
rtk git add app/api.py tests/test_api.py
rtk git commit -m "refactor: make api submit jobs through backend"
```

---

## Task 6: Add Worker Service Execution Loop

**Files:**
- Create: `app/worker_service.py`
- Test: `tests/test_worker_service.py`

- [ ] **Step 1: Write failing worker service tests**

Create `tests/test_worker_service.py`:

```python
import tempfile
import unittest

from app.engines.base import EngineResult
from app.jobs.local import LocalJobBackend
from app.worker_service import run_one_job


class FakeEngine:
    name = "fake"
    capabilities = ("generate",)

    def validate_runtime(self):
        return None

    def run(self, job):
        return EngineResult(output_path=job["output_path"], metadata={"ok": True})


class WorkerServiceTests(unittest.TestCase):
    def test_run_one_job_claims_and_completes_job(self):
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

            worked = run_one_job(backend, FakeEngine(), worker_id="worker-a")

            self.assertTrue(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["output_path"], f"{tmp}/outputs/output_job-1.mp4")

    def test_run_one_job_returns_false_when_queue_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")

            self.assertFalse(run_one_job(backend, FakeEngine(), worker_id="worker-a"))
```

- [ ] **Step 2: Run worker tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_worker_service -v
```

Expected: FAIL because `app.worker_service` does not exist.

- [ ] **Step 3: Create `app/worker_service.py`**

```python
import os
import socket
import time

from app.engines import EngineRegistry, PanoWanEngine
from app.jobs import LocalJobBackend
from app.settings import settings


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PanoWanEngine())
    return registry


def run_one_job(backend: LocalJobBackend, engine, worker_id: str) -> bool:
    job = backend.claim_next_job(worker_id=worker_id)
    if job is None:
        return False
    try:
        result = engine.run(job)
        backend.complete_job(job["job_id"], result.output_path)
        return True
    except Exception as exc:
        backend.fail_job(job["job_id"], str(exc))
        raise


def main() -> None:
    engine_name = os.getenv("ENGINE", "panowan")
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    backend = LocalJobBackend(settings.job_store_path)
    engine = build_registry().get(engine_name)
    engine.validate_runtime()

    print(
        f"Worker started: id={worker_id} engine={engine.name} capabilities={','.join(engine.capabilities)}",
        flush=True,
    )
    while True:
        worked = run_one_job(backend, engine, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run worker tests**

Run:

```bash
rtk test python -m unittest tests.test_worker_service -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add app/worker_service.py tests/test_worker_service.py
rtk git commit -m "feat: add worker job execution service"
```

---

## Task 7: Add API Role Entrypoint

**Files:**
- Create: `app/api_service.py`
- Modify: `app/main.py`
- Test: `tests/test_api_service.py`

- [ ] **Step 1: Write API startup import boundary test**

Create `tests/test_api_service.py`:

```python
import importlib
import sys
import unittest
from unittest import mock


class ApiServiceTests(unittest.TestCase):
    def test_api_service_does_not_import_worker_or_engines_at_startup(self):
        for module_name in list(sys.modules):
            if module_name.startswith("app.api_service") or module_name.startswith("app.worker_service") or module_name.startswith("app.engines"):
                sys.modules.pop(module_name, None)

        importlib.import_module("app.api_service")

        self.assertNotIn("app.worker_service", sys.modules)
        self.assertNotIn("app.engines.panowan", sys.modules)

    @mock.patch("app.api_service.uvicorn.run")
    def test_main_uses_reload_only_in_dev_mode(self, run):
        module = importlib.import_module("app.api_service")
        with mock.patch.dict("os.environ", {"DEV_MODE": "1"}):
            module.main()
        self.assertTrue(run.call_args.kwargs["reload"])
```

- [ ] **Step 2: Run API service tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_api_service -v
```

Expected: FAIL because `app.api_service` does not exist.

- [ ] **Step 3: Create `app/api_service.py`**

```python
import os

import uvicorn

from app.api import app
from app.settings import settings


def main() -> None:
    dev_mode = os.getenv("DEV_MODE", "0") == "1"
    uvicorn.run(
        "app.api:app" if dev_mode else app,
        host=settings.host,
        port=settings.port,
        reload=dev_mode,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Modify `app/main.py` to delegate to API service**

Replace the file with:

```python
from app.api_service import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run API service tests**

Run:

```bash
rtk test python -m unittest tests.test_api_service -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add app/api_service.py app/main.py tests/test_api_service.py
rtk git commit -m "feat: add api role entrypoint"
```

---

## Task 8: Split Runtime Scripts by Role

**Files:**
- Create: `scripts/start-api.sh`
- Create: `scripts/start-worker.sh`
- Create: `scripts/model-setup.sh`
- Create: `scripts/check-runtime.sh`
- Modify: `scripts/lib/env.sh`
- Modify: `scripts/download-models.sh`
- Test: `tests/test_scripts.py`

- [ ] **Step 1: Write script invariant tests**

Create `tests/test_scripts.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScriptBoundaryTests(unittest.TestCase):
    def read_script(self, name):
        return (ROOT / "scripts" / name).read_text(encoding="utf-8")

    def test_start_api_does_not_download_or_check_gpu(self):
        script = self.read_script("start-api.sh")
        self.assertIn("python -m app.api_service", script)
        self.assertNotIn("hf download", script)
        self.assertNotIn("nvidia-smi", script)
        self.assertNotIn("check-runtime.sh", script)

    def test_start_worker_checks_runtime_and_starts_worker(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("check-runtime.sh", script)
        self.assertIn("python -m app.worker_service", script)
        self.assertNotIn("hf download", script)

    def test_model_setup_owns_downloads(self):
        script = self.read_script("model-setup.sh")
        self.assertIn("hf download", script)
        self.assertIn("download-panowan.sh", script)
```

- [ ] **Step 2: Run script tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_scripts -v
```

Expected: FAIL because new scripts do not exist.

- [ ] **Step 3: Update `scripts/lib/env.sh` runtime defaults**

Keep `panowan_env_host()` for host scripts and change runtime defaults to product paths:

```bash
panowan_env_runtime() {
  export SERVICE_ROLE="${SERVICE_ROLE:-api}"
  export RUNTIME_DIR="${RUNTIME_DIR:-/app/runtime}"
  export MODEL_ROOT="${MODEL_ROOT:-/models}"
  export PANOWAN_ENGINE_DIR="${PANOWAN_ENGINE_DIR:-/engines/panowan}"
  export WAN_MODEL_PATH="${WAN_MODEL_PATH:-${MODEL_ROOT}/Wan-AI/Wan2.1-T2V-1.3B}"
  export WAN_DIFFUSION_FILE="${WAN_DIFFUSION_FILE:-${WAN_MODEL_PATH}/diffusion_pytorch_model.safetensors}"
  export WAN_T5_FILE="${WAN_T5_FILE:-${WAN_MODEL_PATH}/models_t5_umt5-xxl-enc-bf16.pth}"
  export LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-${MODEL_ROOT}/PanoWan/latest-lora.ckpt}"
  export OUTPUT_DIR="${OUTPUT_DIR:-${RUNTIME_DIR}/outputs}"
  export JOB_STORE_PATH="${JOB_STORE_PATH:-${RUNTIME_DIR}/jobs.json}"
  export UPSCALE_MODEL_DIR="${UPSCALE_MODEL_DIR:-${MODEL_ROOT}/upscale}"
  export UPSCALE_OUTPUT_DIR="${UPSCALE_OUTPUT_DIR:-${OUTPUT_DIR}}"
}
```

- [ ] **Step 4: Create `scripts/start-api.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

mkdir -p "${RUNTIME_DIR}" "${OUTPUT_DIR}"
cd /app
exec python -m app.api_service
```

- [ ] **Step 5: Create `scripts/check-runtime.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

missing=0

require_path() {
  local path="$1"
  local label="$2"
  if [[ ! -e "${path}" ]]; then
    echo "ERROR: missing ${label}: ${path}" >&2
    missing=1
  fi
}

mkdir -p "${RUNTIME_DIR}" "${OUTPUT_DIR}"
if [[ ! -w "${RUNTIME_DIR}" ]]; then
  echo "ERROR: runtime directory is not writable: ${RUNTIME_DIR}" >&2
  missing=1
fi

require_path "${PANOWAN_ENGINE_DIR}" "PanoWan engine directory"
require_path "${WAN_DIFFUSION_FILE}" "Wan diffusion weights"
require_path "${WAN_T5_FILE}" "Wan T5 weights"
require_path "${LORA_CHECKPOINT_PATH}" "PanoWan LoRA checkpoint"

if [[ "${SERVICE_ROLE:-}" == "worker" ]]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi >/dev/null
  else
    echo "WARNING: nvidia-smi not found; relying on container runtime GPU injection." >&2
  fi
fi

if [[ "${missing}" != "0" ]]; then
  echo "Run: make setup-models" >&2
  exit 1
fi
```

- [ ] **Step 6: Create `scripts/start-worker.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
export SERVICE_ROLE=worker
panowan_env_runtime

bash /app/scripts/check-runtime.sh
cd /app
exec python -m app.worker_service
```

- [ ] **Step 7: Create `scripts/model-setup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

log() {
  printf '[model-setup][%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

mkdir -p "${WAN_MODEL_PATH}" "$(dirname "${LORA_CHECKPOINT_PATH}")" "${UPSCALE_MODEL_DIR}"

if [[ ! -f "${WAN_DIFFUSION_FILE}" ]] || [[ ! -f "${WAN_T5_FILE}" ]]; then
  log "Downloading Wan model weights into ${WAN_MODEL_PATH}"
  export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
  uvx --from="huggingface_hub[cli]" hf download \
    Wan-AI/Wan2.1-T2V-1.3B \
    --local-dir "${WAN_MODEL_PATH}" \
    --max-workers "${HF_MAX_WORKERS:-8}"
else
  log "Wan model weights already present."
fi

if [[ ! -f "${LORA_CHECKPOINT_PATH}" ]]; then
  log "Downloading PanoWan LoRA checkpoint into $(dirname "${LORA_CHECKPOINT_PATH}")"
  cd "${PANOWAN_ENGINE_DIR}"
  bash ./scripts/download-panowan.sh "$(dirname "${LORA_CHECKPOINT_PATH}")"
else
  log "PanoWan LoRA checkpoint already present."
fi

bash /app/scripts/check-runtime.sh
log "Model setup complete."
```

- [ ] **Step 8: Keep `scripts/download-models.sh` as host convenience wrapper**

Update its final message and env semantics so it remains a host-side equivalent of `make setup-models`, using `MODEL_ROOT` and not production startup.

- [ ] **Step 9: Make scripts executable**

Run:

```bash
chmod +x scripts/start-api.sh scripts/start-worker.sh scripts/model-setup.sh scripts/check-runtime.sh
```

- [ ] **Step 10: Run script tests**

Run:

```bash
rtk test python -m unittest tests.test_scripts -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
rtk git add scripts tests/test_scripts.py
rtk git commit -m "refactor: split runtime scripts by service role"
```

---

## Task 9: Replace Dockerfile Targets with Product Runtime Roles

**Files:**
- Modify: `Dockerfile`
- Test: `tests/test_dockerfile.py`

- [ ] **Step 1: Write Dockerfile invariant tests**

Create `tests/test_dockerfile.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerfileTests(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_role_targets_exist(self):
        for target in [
            "runtime-base",
            "api-deps",
            "engine-panowan-deps",
            "api",
            "worker-panowan",
            "dev-api",
            "dev-worker-panowan",
        ]:
            self.assertIn(f" AS {target}", self.dockerfile)

    def test_api_target_does_not_copy_panowan_engine(self):
        api_section = self.dockerfile.split("FROM api-deps AS api", 1)[1].split("FROM", 1)[0]
        self.assertIn("start-api.sh", api_section)
        self.assertNotIn("third_party/PanoWan", api_section)
        self.assertNotIn("/engines/panowan", api_section)

    def test_worker_target_copies_panowan_engine(self):
        worker_section = self.dockerfile.split("FROM engine-panowan-deps AS worker-panowan", 1)[1].split("FROM", 1)[0]
        self.assertIn("/engines/panowan", worker_section)
        self.assertIn("start-worker.sh", worker_section)
```

- [ ] **Step 2: Run Dockerfile tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_dockerfile -v
```

Expected: FAIL because current targets are `prod` and `dev`.

- [ ] **Step 3: Rewrite Dockerfile header and base target**

Use this structure at the top:

```dockerfile
# PanoWan Worker product runtime images
# Targets:
#   api                 CPU-only API and Web UI service
#   worker-panowan      GPU worker with PanoWan engine dependencies
#   dev-api             API development target with reload support
#   dev-worker-panowan  Worker development target with mounted engine/source support

FROM ubuntu:22.04 AS runtime-base

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:${PATH}"

WORKDIR /app

ARG APT_MIRROR=
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|archive.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list \
      && sed -i "s|security.ubuntu.com|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y \
      python3 \
      vmtouch \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
```

- [ ] **Step 4: Add `api-deps` target**

```dockerfile
FROM runtime-base AS api-deps

ARG PYPI_INDEX=
ENV UV_INDEX_URL=${PYPI_INDEX:-}

COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --link-mode=copy
```

- [ ] **Step 5: Add `engine-panowan-deps` target**

```dockerfile
FROM runtime-base AS engine-panowan-deps

ARG PYPI_INDEX=
ENV UV_INDEX_URL=${PYPI_INDEX:-}

COPY third_party/PanoWan/pyproject.toml third_party/PanoWan/uv.lock /tmp/PanoWan/
WORKDIR /tmp/PanoWan
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --link-mode=copy
```

- [ ] **Step 6: Add `api` target**

```dockerfile
FROM api-deps AS api

WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts
RUN mkdir -p /app/runtime
EXPOSE 8000
CMD ["bash", "/app/scripts/start-api.sh"]
```

- [ ] **Step 7: Add `worker-panowan` target**

```dockerfile
FROM engine-panowan-deps AS worker-panowan

WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts
COPY third_party/PanoWan /engines/panowan
RUN mkdir -p /app/runtime /models
EXPOSE 8000
CMD ["bash", "/app/scripts/start-worker.sh"]
```

- [ ] **Step 8: Add dev targets**

```dockerfile
FROM api-deps AS dev-api

WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --link-mode=copy
EXPOSE 8000
CMD ["bash", "/app/scripts/start-api.sh"]

FROM engine-panowan-deps AS dev-worker-panowan

WORKDIR /app
COPY app /app/app
COPY scripts /app/scripts
COPY third_party/PanoWan /engines/panowan
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/PanoWan && uv sync --locked --no-install-project --link-mode=copy
CMD ["bash", "/app/scripts/start-worker.sh"]
```

- [ ] **Step 9: Run Dockerfile invariant tests**

Run:

```bash
rtk test python -m unittest tests.test_dockerfile -v
```

Expected: PASS.

- [ ] **Step 10: Build API target**

Run:

```bash
rtk docker build --target api -t panowan-api:test .
```

Expected: image builds without installing PanoWan dependencies.

- [ ] **Step 11: Build worker target**

Run:

```bash
rtk docker build --target worker-panowan -t panowan-worker-panowan:test .
```

Expected: image builds with PanoWan dependencies and `/engines/panowan` source.

- [ ] **Step 12: Commit**

```bash
rtk git add Dockerfile tests/test_dockerfile.py
rtk git commit -m "build: split docker targets by runtime role"
```

---

## Task 10: Replace Compose Topology with API, Worker, and Model Setup

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose-dev.yml`
- Test: `tests/test_compose.py`

- [ ] **Step 1: Write Compose invariant tests**

Create `tests/test_compose.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ComposeTests(unittest.TestCase):
    def test_production_compose_uses_split_services(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("api:", compose)
        self.assertIn("worker-panowan:", compose)
        self.assertIn("model-setup:", compose)
        self.assertNotIn("panowan:", compose)

    def test_api_service_has_no_gpu_or_model_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        api_section = compose.split("  api:", 1)[1].split("  worker-panowan:", 1)[0]
        self.assertIn("target: api", api_section)
        self.assertNotIn("gpus:", api_section)
        self.assertNotIn(":/models", api_section)

    def test_worker_service_has_gpu_and_model_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        worker_section = compose.split("  worker-panowan:", 1)[1].split("  model-setup:", 1)[0]
        self.assertIn("target: worker-panowan", worker_section)
        self.assertIn("gpus: all", worker_section)
        self.assertIn(":/models", worker_section)
```

- [ ] **Step 2: Run Compose tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_compose -v
```

Expected: FAIL because current Compose has one `panowan` service.

- [ ] **Step 3: Replace `docker-compose.yml`**

```yaml
services:
  api:
    build:
      context: .
      target: api
      args:
        APT_MIRROR: ${APT_MIRROR:-}
        PYPI_INDEX: ${PYPI_INDEX:-}
    image: panowan-api:${TAG:-latest}
    ports:
      - "${PORT:-8000}:8000"
    env_file:
      - path: .env
        required: false
    environment:
      SERVICE_ROLE: api
      HOST: 0.0.0.0
      RUNTIME_DIR: /app/runtime
      JOB_BACKEND: local
    volumes:
      - ./data/runtime:/app/runtime
    restart: unless-stopped

  worker-panowan:
    build:
      context: .
      target: worker-panowan
      args:
        APT_MIRROR: ${APT_MIRROR:-}
        PYPI_INDEX: ${PYPI_INDEX:-}
    image: panowan-worker-panowan:${TAG:-latest}
    env_file:
      - path: .env
        required: false
    environment:
      SERVICE_ROLE: worker
      ENGINE: panowan
      CAPABILITIES: t2v,i2v,upscale
      RUNTIME_DIR: /app/runtime
      MODEL_ROOT: /models
      PANOWAN_ENGINE_DIR: /engines/panowan
      JOB_BACKEND: local
      TORCH_CUDNN_V8_API_ENABLED: "1"
      CUDA_MODULE_LOADING: LAZY
    volumes:
      - ${MODEL_ROOT:-./data/models}:/models
      - ./data/runtime:/app/runtime
    gpus: all
    restart: unless-stopped

  model-setup:
    build:
      context: .
      target: worker-panowan
      args:
        APT_MIRROR: ${APT_MIRROR:-}
        PYPI_INDEX: ${PYPI_INDEX:-}
    image: panowan-worker-panowan:${TAG:-latest}
    profiles: ["setup"]
    command: ["bash", "/app/scripts/model-setup.sh"]
    env_file:
      - path: .env
        required: false
    environment:
      MODEL_ROOT: /models
      PANOWAN_ENGINE_DIR: /engines/panowan
    volumes:
      - ${MODEL_ROOT:-./data/models}:/models
```

- [ ] **Step 4: Replace `docker-compose-dev.yml`**

```yaml
services:
  api:
    build:
      target: dev-api
    environment:
      DEV_MODE: "1"
    volumes:
      - ./app:/app/app
      - ./scripts:/app/scripts
      - ./data/runtime:/app/runtime
    restart: "no"

  worker-panowan:
    build:
      target: dev-worker-panowan
    environment:
      DEV_MODE: "1"
      UV_LINK_MODE: copy
    volumes:
      - panowan-uv-cache:/root/.cache/uv
      - ./app:/app/app
      - ./scripts:/app/scripts
      - ./third_party/PanoWan:/engines/panowan
      - ${MODEL_ROOT:-./data/models}:/models
      - ./data/runtime:/app/runtime
    restart: "no"

  model-setup:
    build:
      target: dev-worker-panowan
    volumes:
      - panowan-uv-cache:/root/.cache/uv
      - ./scripts:/app/scripts
      - ./third_party/PanoWan:/engines/panowan
      - ${MODEL_ROOT:-./data/models}:/models

volumes:
  panowan-uv-cache:
```

- [ ] **Step 5: Validate Compose config**

Run:

```bash
rtk docker compose -f docker-compose.yml config
rtk docker compose -f docker-compose.yml -f docker-compose-dev.yml config
```

Expected: both commands render valid Compose configuration.

- [ ] **Step 6: Run Compose tests**

Run:

```bash
rtk test python -m unittest tests.test_compose -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add docker-compose.yml docker-compose-dev.yml tests/test_compose.py
rtk git commit -m "build: express product runtime compose topology"
```

---

## Task 11: Replace Makefile Interface with Explicit Role Commands

**Files:**
- Modify: `Makefile`
- Test: `tests/test_makefile.py`

- [ ] **Step 1: Write Makefile invariant tests**

Create `tests/test_makefile.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MakefileTests(unittest.TestCase):
    def setUp(self):
        self.makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    def test_explicit_role_commands_exist(self):
        for target in ["build-dev", "setup-models", "up-dev", "down-dev", "logs-dev"]:
            self.assertRegex(self.makefile, rf"(^|\n){target}:")

    def test_no_dev_mode_compose_file_switch(self):
        self.assertNotIn("ifeq ($(DEV),1)", self.makefile)
        self.assertNotIn("COMPOSE_FILE := docker-compose-dev.yml", self.makefile)
```

- [ ] **Step 2: Run Makefile tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_makefile -v
```

Expected: FAIL because current Makefile uses `DEV=1` switching.

- [ ] **Step 3: Replace Makefile Compose variables**

Use explicit Compose commands:

```makefile
DOCKER ?= bash scripts/docker-proxy.sh
COMPOSE_PROD ?= $(DOCKER) compose -f docker-compose.yml
COMPOSE_DEV ?= $(DOCKER) compose -f docker-compose.yml -f docker-compose-dev.yml
SERVICE_URL ?= http://localhost:8000
TAG ?= latest
export TAG

APT_MIRROR ?=
PYPI_INDEX ?=
BUILD_ARGS := $(if $(APT_MIRROR),--build-arg APT_MIRROR=$(APT_MIRROR)) $(if $(PYPI_INDEX),--build-arg PYPI_INDEX=$(PYPI_INDEX))

ifneq (,$(wildcard .env))
include .env
endif

NORMALIZE_BIND_PATH ?= bash scripts/lib/path.sh

define normalize_bind_var
ifneq ($(strip $($(1))),)
export $(1) := $(shell $(NORMALIZE_BIND_PATH) "$($(1))")
endif
endef

$(eval $(call normalize_bind_var,MODEL_ROOT))
```

- [ ] **Step 4: Replace `.PHONY` list**

```makefile
.PHONY: init submodule env test build build-dev setup-models up up-dev down down-dev logs logs-dev health doctor download-models docker-env
```

- [ ] **Step 5: Replace build/up/down/log targets**

```makefile
test:
	python -m unittest discover -s tests

build:
	$(COMPOSE_PROD) build $(BUILD_ARGS)

build-dev:
	$(COMPOSE_DEV) build $(BUILD_ARGS)

setup-models:
	$(COMPOSE_PROD) run --rm --profile setup model-setup

up:
	$(COMPOSE_PROD) up -d $(UP_FLAGS)

up-dev:
	$(COMPOSE_DEV) up -d $(UP_FLAGS)

down:
	$(COMPOSE_PROD) down

down-dev:
	$(COMPOSE_DEV) down

logs:
	$(COMPOSE_PROD) logs -f

logs-dev:
	$(COMPOSE_DEV) logs -f
```

- [ ] **Step 6: Keep health, doctor, host download, docker-env targets**

Update `docker-env` to print both Compose commands:

```makefile
docker-env:
	@echo "DOCKER=$(DOCKER)"
	@echo "COMPOSE_PROD=$(COMPOSE_PROD)"
	@echo "COMPOSE_DEV=$(COMPOSE_DEV)"
	@echo "TAG=$(TAG)"
	@$(DOCKER) version --format '{{.Server.Version}}' 2>/dev/null || echo "docker daemon unavailable"
```

- [ ] **Step 7: Run Makefile tests**

Run:

```bash
rtk test python -m unittest tests.test_makefile -v
```

Expected: PASS.

- [ ] **Step 8: Validate Makefile targets render commands**

Run:

```bash
rtk make -n build
rtk make -n build-dev
rtk make -n setup-models
rtk make -n up
rtk make -n up-dev
```

Expected: commands reference `docker-compose.yml` for production and both files for dev.

- [ ] **Step 9: Commit**

```bash
rtk git add Makefile tests/test_makefile.py
rtk git commit -m "build: add explicit compose role commands"
```

---

## Task 12: Rewrite Environment Template Around Product Runtime

**Files:**
- Modify: `.env.example`
- Test: `tests/test_env_example.py`

- [ ] **Step 1: Write `.env.example` tests**

Create `tests/test_env_example.py`:

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnvExampleTests(unittest.TestCase):
    def setUp(self):
        self.env = (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_product_runtime_variables_exist(self):
        for key in [
            "RUNTIME_DIR=",
            "JOB_BACKEND=",
            "ENGINE=",
            "CAPABILITIES=",
            "MODEL_ROOT=",
            "PANOWAN_ENGINE_DIR=",
            "WAN_MODEL_PATH=",
            "LORA_CHECKPOINT_PATH=",
            "UPSCALE_MODEL_DIR=",
        ]:
            self.assertIn(key, self.env)

    def test_legacy_panowan_app_dir_is_not_primary_configuration(self):
        self.assertNotIn("PANOWAN_APP_DIR=", self.env)
```

- [ ] **Step 2: Run env tests and verify failure**

Run:

```bash
rtk test python -m unittest tests.test_env_example -v
```

Expected: FAIL because current `.env.example` is all-in-one oriented.

- [ ] **Step 3: Replace `.env.example` content**

Use:

```env
# ─── PanoWan Worker — product runtime configuration ───────────────────────────
# Copy to .env and override values as needed. Docker Compose auto-loads .env.

# ─── API service ──────────────────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8000

# ─── Product runtime ──────────────────────────────────────────────────────────
RUNTIME_DIR=/app/runtime
JOB_BACKEND=local
WORKER_POLL_INTERVAL_SECONDS=2

# ─── Worker ───────────────────────────────────────────────────────────────────
ENGINE=panowan
CAPABILITIES=t2v,i2v,upscale
MAX_CONCURRENT_JOBS=1

# ─── Model assets ─────────────────────────────────────────────────────────────
# In Compose, host MODEL_ROOT is bind-mounted to /models in worker/model-setup.
MODEL_ROOT=./data/models
WAN_MODEL_PATH=/models/Wan-AI/Wan2.1-T2V-1.3B
LORA_CHECKPOINT_PATH=/models/PanoWan/latest-lora.ckpt
UPSCALE_MODEL_DIR=/models/upscale
UPSCALE_OUTPUT_DIR=/app/runtime/outputs

# ─── PanoWan engine ───────────────────────────────────────────────────────────
PANOWAN_ENGINE_DIR=/engines/panowan

# ─── Generation defaults ──────────────────────────────────────────────────────
GENERATION_TIMEOUT_SECONDS=1800
DEFAULT_NUM_INFERENCE_STEPS=50
DEFAULT_WIDTH=896
DEFAULT_HEIGHT=448
# DEFAULT_PROMPT=A beautiful mountain landscape at sunset

# ─── Hugging Face downloads ───────────────────────────────────────────────────
HF_TOKEN=
HF_ENDPOINT=https://hf-mirror.com
HF_HUB_ENABLE_HF_TRANSFER=0
HF_HUB_DOWNLOAD_TIMEOUT=10
HF_MAX_WORKERS=8

# ─── Build mirrors ────────────────────────────────────────────────────────────
# APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
# PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# ─── PyTorch and performance ──────────────────────────────────────────────────
PYTORCH_ALLOC_CONF=expandable_segments:True
TORCH_CUDNN_V8_API_ENABLED=1
CUDA_MODULE_LOADING=LAZY
VMTOUCH_MODELS=0

# ─── Upscale ──────────────────────────────────────────────────────────────────
UPSCALE_TIMEOUT_SECONDS=1800
```

- [ ] **Step 4: Run env tests**

Run:

```bash
rtk test python -m unittest tests.test_env_example -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add .env.example tests/test_env_example.py
rtk git commit -m "docs: align env template with product runtime roles"
```

---

## Task 13: Update README and Architecture Docs After Implementation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/product-runtime.md`
- Modify: `docs/architecture/adr/0001-engine-oriented-product-runtime.md`

- [ ] **Step 1: Update README quick start commands**

Replace all-in-one quick start commands with:

```bash
make init
make doctor
make setup-models
make build
make up
make health
```

Replace dev workflow with:

```bash
make build-dev
make up-dev
make logs-dev
```

- [ ] **Step 2: Update README Compose role section**

State that the default Compose topology now contains:

```text
api
worker-panowan
model-setup
```

Remove wording that says implementation is still pre-rearchitecture for Docker/Compose after this implementation lands.

- [ ] **Step 3: Update Makefile quick reference**

Use:

```bash
make env           # initialize .env
make doctor        # diagnose host Docker/GPU/model state
make setup-models  # run one-shot model setup container
make build         # build production api + worker images
make build-dev     # build development api + worker images
make up            # start split production topology
make up-dev        # start split topology with dev overrides
make down          # stop production topology
make down-dev      # stop development topology
make logs          # follow production logs
make logs-dev      # follow development logs
make health        # check API health endpoint
make test          # run unit tests
```

- [ ] **Step 4: Update architecture implementation status**

In `docs/architecture/product-runtime.md`, change status to:

```markdown
Status: Accepted direction, initial Docker/Compose implementation complete
```

Add one short implementation note listing `docker-compose.yml`, `docker-compose-dev.yml`, and Dockerfile role targets.

- [ ] **Step 5: Update ADR implementation note**

Add:

```markdown
## Implementation Notes

The initial implementation uses Dockerfile targets `api`, `worker-panowan`, `dev-api`, and `dev-worker-panowan`. The default Compose topology exposes `api`, `worker-panowan`, and a profiled `model-setup` service.
```

- [ ] **Step 6: Search docs for stale all-in-one claims**

Run:

```bash
rtk grep "all-in-one|DEV=1|prod target|dev target|docker-compose-dev.yml up|panowan:" README.md docs .env.example
```

Expected: only historical/contextual mentions remain, not current quick-start instructions.

- [ ] **Step 7: Commit**

```bash
rtk git add README.md docs/architecture/product-runtime.md docs/architecture/adr/0001-engine-oriented-product-runtime.md
rtk git commit -m "docs: document split product runtime implementation"
```

---

## Task 14: Run Full Verification Matrix

**Files:**
- Inspect only unless failures require fixes in previously touched files.

- [ ] **Step 1: Run full unit test suite on Windows host Python**

Run:

```bash
rtk test python -m unittest discover -s tests
```

Expected: PASS. If failures are Windows-vs-container path related, fix the product path helper or tests rather than reverting to `os.path.join` for container paths.

- [ ] **Step 2: Validate Compose configs**

Run:

```bash
rtk docker compose -f docker-compose.yml config
rtk docker compose -f docker-compose.yml -f docker-compose-dev.yml config
```

Expected: PASS.

- [ ] **Step 3: Build production images**

Run:

```bash
rtk make build
```

Expected: `panowan-api:${TAG:-latest}` and `panowan-worker-panowan:${TAG:-latest}` build successfully.

- [ ] **Step 4: Verify API image does not contain PanoWan engine source**

Run:

```bash
rtk docker run --rm panowan-api:${TAG:-latest} python - <<'PY'
from pathlib import Path
print(Path('/engines/panowan').exists())
PY
```

Expected output: `False`.

- [ ] **Step 5: Verify API service starts without GPU/model mounts**

Run:

```bash
rtk docker compose -f docker-compose.yml up -d api
rtk docker compose -f docker-compose.yml logs api
rtk curl http://localhost:8000/health
rtk docker compose -f docker-compose.yml down
```

Expected: API starts and `/health` responds without CUDA, torch, PanoWan source, or model files.

- [ ] **Step 6: Validate worker missing-assets failure message**

Run with an empty temporary model root:

```bash
MODEL_ROOT=./data/empty-models rtk docker compose -f docker-compose.yml up worker-panowan
```

Expected: worker exits with a message naming missing model/LoRA files and `Run: make setup-models`. Remove `data/empty-models` only after confirming it contains no user assets.

- [ ] **Step 7: Validate model setup command shape without forcing downloads**

Run:

```bash
rtk make -n setup-models
```

Expected: command uses Compose `model-setup` profile. Do not run real model downloads unless the user explicitly wants a full runtime validation.

- [ ] **Step 8: Build development images**

Run:

```bash
rtk make build-dev
```

Expected: dev API and dev worker targets build.

- [ ] **Step 9: Final git status review**

Run:

```bash
rtk git status
rtk git diff --stat
```

Expected: no unstaged changes if all task commits succeeded.

---

## Self-Review

- Spec coverage: The plan covers product dependency ownership, API/Worker/Model Setup roles, engine boundary, local job backend, Dockerfile targets, Compose topology, Makefile commands, environment model, documentation updates, and validation strategy from `docs/superpowers/specs/2026-04-24-docker-compose-product-runtime-rearchitecture-design.md`.
- Placeholder scan: The plan contains no unresolved placeholder instructions or vague implementation steps.
- Type consistency: The plan consistently uses `LocalJobBackend`, `EngineResult`, `EngineRegistry`, `PanoWanEngine`, `settings.panowan_engine_dir`, `settings.model_root`, and Docker targets `api`, `worker-panowan`, `dev-api`, and `dev-worker-panowan`.
- Risk note: Task 5 is the highest-risk task because it changes runtime semantics from FastAPI BackgroundTasks to worker polling. Keep it isolated and do not start Docker/Compose rewrites until Task 5 and Task 6 tests pass.
