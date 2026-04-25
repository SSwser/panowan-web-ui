# Upscale Backend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement backend-level readiness gating for `UpscaleEngine` so only runnable upscale models are exposed, and convert RealESRGAN from an environment-variable bridge into a deterministic backend contract.

**Architecture:** `UPSCALE_BACKENDS` remains the registered catalog, while a new availability helper filters that catalog against declared engine files, weight files, and required commands. API job creation and worker startup use available backends, not the raw registry. RealESRGAN becomes the first complete backend under `/engines/upscale/realesrgan` and `/models/upscale/realesrgan`; RealBasicVSR and SeedVR2 stay registered metadata only until their assets and dependencies are present.

**Tech Stack:** Python 3.12, FastAPI, unittest, Docker, bash wrappers, existing `app.models` ModelManager.

---

## File Structure

- Modify: `app/upscaler.py`
  - Add `UpscaleBackendAssets` dataclass.
  - Add `assets` declarations to backend classes.
  - Add `get_available_upscale_backends()` helper.
  - Change RealESRGAN command to call `realesrgan/adapter.py`.
- Modify: `app/api.py`
  - Validate `POST /upscale` against available backends.
  - Keep parameter validation backend-specific.
- Modify: `app/engines/upscale.py`
  - Validate that at least one backend is available at worker startup.
  - Pass settings paths unchanged into `upscale_video()`.
- Modify: `app/models/providers.py`
  - Add `HttpProvider` for direct model artifacts.
  - Download via temporary file and publish only after verification succeeds.
- Modify: `app/models/manager.py`
  - Register the `http` source type.
- Modify: `app/models/specs.py`
  - Change RealESRGAN engine spec from bridge file to adapter + vendored runner files.
  - Rename specs from generic `upscale-engine` / `realesrgan-weights` to backend-specific RealESRGAN names.
  - Change RealESRGAN weights from the non-authoritative HuggingFace repo to the official Real-ESRGAN release artifact.
- Create: `third_party/Upscale/realesrgan/adapter.py`
  - Deterministically executes `vendor/inference_realesrgan_video.py`.
- Move/replace: `third_party/Upscale/realesrgan/inference_realesrgan_video.py`
  - Remove bridge behavior from target execution path. Keep no env-var fallback.
- Create: `third_party/Upscale/realesrgan/vendor/.gitkeep`
  - Keep vendored runner directory present until the real upstream runner is added.
- Modify: `third_party/Upscale/README.md`
  - Document backend directory contract and readiness semantics.
- Modify: `docs/superpowers/plans/2026-04-25-model-download-manager.md`
  - Fix stale `${MODEL_ROOT}/realesrgan` text.
- Modify: `docs/superpowers/specs/2026-04-25-model-download-manager-design.md`
  - Fix RealBasicVSR / SeedVR2 line to refer to backend subdirectories under generic upscale dirs.
- Modify: `tests/test_upscaler.py`
  - Split registered catalog tests from availability tests.
- Modify: `tests/test_api.py`
  - Add API rejection for registered-but-unavailable models.
  - Ensure available RealESRGAN still creates an upscale job.
- Modify: `tests/test_engines.py`
  - Add `UpscaleEngine.validate_runtime()` available-backend behavior.
- Modify: `tests/test_models.py`
  - Update expected ModelSpec names and RealESRGAN engine file checks.

---

### Task 1: Add direct HTTP model artifact provider

**Files:**
- Modify: `app/models/providers.py`
- Modify: `app/models/manager.py`
- Modify: `app/models/specs.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for direct artifact source support**

Add or update tests in `tests/test_models.py` for these behaviors:

- `load_specs()` emits `upscale-realesrgan-weights` with `source_type == "http"`.
- The RealESRGAN weight spec uses the official release artifact URL:

```text
https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth
```

- `ModelManager` supports `source_type="http"`.
- `HttpProvider.ensure()` skips download when the target file exists and checksum validation passes.
- `HttpProvider.ensure()` downloads to a temporary file in `spec.target_dir`, verifies the declared `FileCheck`, and atomically publishes the final file.
- `HttpProvider.verify()` fails on missing files and checksum mismatch.

Patch network access in tests; do not hit GitHub from unit tests.

- [ ] **Step 2: Run the failing model provider tests**

Run:

```bash
rtk python -m pytest tests/test_models.py -v
```

Expected: fail because `http` source type and `HttpProvider` do not exist yet, and RealESRGAN still uses the old HuggingFace source.

- [ ] **Step 3: Implement `HttpProvider`**

In `app/models/providers.py`, add a provider that:

- treats `spec.source_ref` as a direct URL,
- supports exactly one file per direct-artifact spec,
- creates `spec.target_dir` before downloading,
- downloads into a temporary file in the target directory,
- verifies the downloaded file using existing `FileCheck.sha256` support when present,
- replaces the final path with `os.replace()` only after verification succeeds,
- removes the temporary file on failure.

Suggested shape:

```python
class HttpProvider:
    def _all_files_present(self, spec: ModelSpec) -> bool:
        for file_check in spec.files:
            full_path = os.path.join(spec.target_dir, file_check.path)
            if not os.path.isfile(full_path):
                return False
            if file_check.sha256 and not _check_sha256(full_path, file_check.sha256):
                return False
        return True

    def verify(self, spec: ModelSpec) -> None:
        for file_check in spec.files:
            full_path = os.path.join(spec.target_dir, file_check.path)
            if not os.path.isfile(full_path):
                raise FileNotFoundError(
                    f"Missing model file: {full_path} (spec: {spec.name})"
                )
            if file_check.sha256 and not _check_sha256(full_path, file_check.sha256):
                raise RuntimeError(f"Hash mismatch for {full_path} (spec: {spec.name})")

    def ensure(self, spec: ModelSpec) -> None:
        if self._all_files_present(spec):
            return
        if len(spec.files) != 1:
            raise RuntimeError(f"HTTP model spec must declare exactly one file: {spec.name}")
        ...
```

Use Python stdlib (`urllib.request`) unless a project dependency already exists for HTTP downloads.

- [ ] **Step 4: Register `http` source type**

In `app/models/manager.py`, register:

```python
"http": HttpProvider(),
```

next to the existing `huggingface` and `submodule` providers.

- [ ] **Step 5: Switch RealESRGAN weights to official direct artifact**

In `app/models/specs.py`, replace the old `realesrgan-weights` spec with:

```python
ModelSpec(
    name="upscale-realesrgan-weights",
    source_type="http",
    source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
    target_dir=container_child(settings.upscale_weights_dir, "realesrgan"),
    files=[FileCheck(path="realesr-animevideov3.pth", sha256="<verified-sha256>")],
),
```

Before finalizing implementation, replace `<verified-sha256>` with the digest computed from the downloaded official artifact. Do not leave a fake checksum.

- [ ] **Step 6: Run model-manager tests**

Run:

```bash
rtk python -m pytest tests/test_models.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
rtk git add app/models/providers.py app/models/manager.py app/models/specs.py tests/test_models.py
rtk git commit -m "feat: support direct model artifact downloads"
```

---

### Task 2: Add backend asset metadata and availability filtering

**Files:**
- Modify: `app/upscaler.py`
- Test: `tests/test_upscaler.py`

- [ ] **Step 1: Write failing tests for asset metadata and availability**

Add these tests to `tests/test_upscaler.py` near `UpscalerRegistryTests`:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.upscaler import get_available_upscale_backends


class UpscalerAvailabilityTests(unittest.TestCase):
    def test_registered_backends_declare_assets(self) -> None:
        for backend in UPSCALE_BACKENDS.values():
            self.assertTrue(backend.assets.engine_files)
            self.assertIsInstance(backend.assets.weight_files, tuple)
            self.assertIsInstance(backend.assets.required_commands, tuple)

    def test_backend_unavailable_when_engine_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as engine_dir, tempfile.TemporaryDirectory() as weights_dir:
            Path(weights_dir, "realesrgan").mkdir(parents=True)
            Path(weights_dir, "realesrgan", "realesr-animevideov3.pth").write_text("x")

            available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)

    def test_backend_unavailable_when_weight_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as engine_dir, tempfile.TemporaryDirectory() as weights_dir:
            Path(engine_dir, "realesrgan", "vendor").mkdir(parents=True)
            Path(engine_dir, "realesrgan", "adapter.py").write_text("x")
            Path(engine_dir, "realesrgan", "vendor", "inference_realesrgan_video.py").write_text("x")

            available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)

    def test_backend_available_when_assets_exist(self) -> None:
        with tempfile.TemporaryDirectory() as engine_dir, tempfile.TemporaryDirectory() as weights_dir:
            Path(engine_dir, "realesrgan", "vendor").mkdir(parents=True)
            Path(engine_dir, "realesrgan", "adapter.py").write_text("x")
            Path(engine_dir, "realesrgan", "vendor", "inference_realesrgan_video.py").write_text("x")
            Path(weights_dir, "realesrgan").mkdir(parents=True)
            Path(weights_dir, "realesrgan", "realesr-animevideov3.pth").write_text("x")

            available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertIn("realesrgan-animevideov3", available)

    def test_backend_unavailable_when_required_command_missing(self) -> None:
        with tempfile.TemporaryDirectory() as engine_dir, tempfile.TemporaryDirectory() as weights_dir:
            Path(engine_dir, "seedvr2", "projects").mkdir(parents=True)
            Path(engine_dir, "seedvr2", "projects", "inference_seedvr2_3b.py").write_text("x")
            Path(weights_dir, "seedvr2").mkdir(parents=True)
            for filename in (
                "seedvr2_ema_3b.pth",
                "ema_vae.pth",
                "pos_emb.pt",
                "neg_emb.pt",
            ):
                Path(weights_dir, "seedvr2", filename).write_text("x")

            with patch("app.upscaler.shutil.which", return_value=None):
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("seedvr2-3b", available)
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
rtk python -m pytest tests/test_upscaler.py::UpscalerAvailabilityTests -v
```

Expected: fail because `get_available_upscale_backends` and `assets` do not exist.

- [ ] **Step 3: Implement backend assets and availability helper**

Update the imports at the top of `app/upscaler.py`:

```python
from dataclasses import dataclass
import os
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
```

Add this dataclass above `UpscalerBackend`:

```python
@dataclass(frozen=True)
class UpscaleBackendAssets:
    engine_files: tuple[str, ...]
    weight_files: tuple[str, ...]
    required_commands: tuple[str, ...] = ()
```

Add `assets` to the protocol:

```python
@runtime_checkable
class UpscalerBackend(Protocol):
    name: str
    display_name: str
    default_scale: int
    max_scale: int
    assets: UpscaleBackendAssets
```

Add assets to `RealESRGANBackend`:

```python
assets = UpscaleBackendAssets(
    engine_files=(
        "realesrgan/adapter.py",
        "realesrgan/vendor/inference_realesrgan_video.py",
    ),
    weight_files=("realesrgan/realesr-animevideov3.pth",),
)
```

Add assets to `RealBasicVSRBackend`:

```python
assets = UpscaleBackendAssets(
    engine_files=(
        "realbasicvsr/adapter.py",
        "realbasicvsr/configs/realbasicvsr_x4.py",
    ),
    weight_files=("realbasicvsr/RealBasicVSR_x4.pth",),
)
```

Add assets to `SeedVR2Backend`:

```python
assets = UpscaleBackendAssets(
    engine_files=("seedvr2/projects/inference_seedvr2_3b.py",),
    weight_files=(
        "seedvr2/seedvr2_ema_3b.pth",
        "seedvr2/ema_vae.pth",
        "seedvr2/pos_emb.pt",
        "seedvr2/neg_emb.pt",
    ),
    required_commands=("torchrun",),
)
```

Add these helpers below `UPSCALE_BACKENDS`:

```python
def _has_backend_assets(
    backend: UpscalerBackend,
    engine_dir: str,
    weights_dir: str,
) -> bool:
    for relative_path in backend.assets.engine_files:
        if not os.path.exists(container_join(engine_dir, relative_path)):
            return False
    for relative_path in backend.assets.weight_files:
        if not os.path.exists(container_join(weights_dir, relative_path)):
            return False
    for command in backend.assets.required_commands:
        if shutil.which(command) is None:
            return False
    return True


def get_available_upscale_backends(
    engine_dir: str,
    weights_dir: str,
    backends: Mapping[str, UpscalerBackend] = UPSCALE_BACKENDS,
) -> dict[str, UpscalerBackend]:
    return {
        name: backend
        for name, backend in backends.items()
        if _has_backend_assets(backend, engine_dir, weights_dir)
    }
```

- [ ] **Step 4: Run availability tests**

Run:

```bash
rtk python -m pytest tests/test_upscaler.py::UpscalerAvailabilityTests -v
```

Expected: pass.

- [ ] **Step 5: Run all upscaler tests**

Run:

```bash
rtk python -m pytest tests/test_upscaler.py -v
```

Expected: existing RealESRGAN command test fails because command still points to `inference_realesrgan_video.py`; this is fixed in Task 3. If only availability tests pass and command tests fail for the adapter path, continue.

- [ ] **Step 6: Commit**

```bash
rtk git add app/upscaler.py tests/test_upscaler.py
rtk git commit -m "feat: add upscale backend availability checks"
```

---

### Task 3: Gate API upscale job creation by available backends

**Files:**
- Modify: `app/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

In `tests/test_api.py`, add imports if missing:

```python
from pathlib import Path
from unittest.mock import patch
```

Add tests near existing upscale tests:

```python
def test_upscale_rejects_registered_but_unavailable_model(self) -> None:
    source_job = self._create_completed_job()

    with patch("app.api.get_available_upscale_backends", return_value={}):
        response = self.client.post(
            "/upscale",
            json={
                "source_job_id": source_job["job_id"],
                "model": "realesrgan-animevideov3",
            },
        )

    self.assertEqual(response.status_code, 400)
    self.assertIn("not available", response.json()["detail"])


def test_upscale_accepts_available_model(self) -> None:
    source_job = self._create_completed_job()

    with patch("app.api.get_available_upscale_backends", return_value={"realesrgan-animevideov3": UPSCALE_BACKENDS["realesrgan-animevideov3"]}):
        response = self.client.post(
            "/upscale",
            json={
                "source_job_id": source_job["job_id"],
                "model": "realesrgan-animevideov3",
            },
        )

    self.assertEqual(response.status_code, 202)
    self.assertEqual(response.json()["upscale_params"]["model"], "realesrgan-animevideov3")
```

If this test class does not already have `_create_completed_job()`, use the existing completed-job helper in the file. If the file uses inline job creation, copy that same pattern and patch `os.path.exists` only for the source output file.

- [ ] **Step 2: Run the failing API tests**

Run:

```bash
rtk python -m pytest tests/test_api.py -k "upscale and available" -v
```

Expected: fail because `app.api.get_available_upscale_backends` is not imported or used.

- [ ] **Step 3: Update API imports**

Change the `app/api.py` upscaler import to:

```python
from .upscaler import UPSCALE_BACKENDS, get_available_upscale_backends
```

- [ ] **Step 4: Update `/upscale` model validation**

Replace this block in `app/api.py`:

```python
model_name = payload.get("model", "realesrgan-animevideov3")
backend = UPSCALE_BACKENDS.get(model_name)
if backend is None:
    raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")
```

with:

```python
model_name = payload.get("model", "realesrgan-animevideov3")
if model_name not in UPSCALE_BACKENDS:
    raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")

available_backends = get_available_upscale_backends(
    settings.upscale_engine_dir,
    settings.upscale_weights_dir,
)
backend = available_backends.get(model_name)
if backend is None:
    available = ", ".join(available_backends.keys()) or "none"
    raise HTTPException(
        status_code=400,
        detail=(
            f"Model '{model_name}' is not available in this worker runtime. "
            f"Available models: {available}"
        ),
    )
```

- [ ] **Step 5: Run API tests**

Run:

```bash
rtk python -m pytest tests/test_api.py -k upscale -v
```

Expected: pass after adjusting helper usage to this repo's exact test patterns.

- [ ] **Step 6: Commit**

```bash
rtk git add app/api.py tests/test_api.py
rtk git commit -m "feat: gate upscale API by available backends"
```

---

### Task 4: Validate available upscale backends at worker startup

**Files:**
- Modify: `app/engines/upscale.py`
- Test: `tests/test_engines.py`

- [ ] **Step 1: Write failing engine validation tests**

Add these tests to `tests/test_engines.py` near existing `UpscaleEngine` tests:

```python
from unittest.mock import patch

from app.engines.upscale import UpscaleEngine


class UpscaleEngineRuntimeValidationTests(unittest.TestCase):
    def test_validate_runtime_fails_when_no_backend_available(self) -> None:
        engine = UpscaleEngine()

        with patch("app.engines.upscale.get_available_upscale_backends", return_value={}):
            with self.assertRaises(FileNotFoundError) as ctx:
                engine.validate_runtime()

        self.assertIn("No available upscale backends", str(ctx.exception))

    def test_validate_runtime_passes_when_backend_available(self) -> None:
        engine = UpscaleEngine()

        with patch(
            "app.engines.upscale.get_available_upscale_backends",
            return_value={"realesrgan-animevideov3": object()},
        ):
            engine.validate_runtime()
```

- [ ] **Step 2: Run failing engine tests**

Run:

```bash
rtk python -m pytest tests/test_engines.py::UpscaleEngineRuntimeValidationTests -v
```

Expected: fail because `UpscaleEngine.validate_runtime()` only checks top-level directories.

- [ ] **Step 3: Update `app/engines/upscale.py` imports**

Change:

```python
from app.upscaler import upscale_video
```

to:

```python
from app.upscaler import get_available_upscale_backends, upscale_video
```

- [ ] **Step 4: Update runtime validation**

Replace `validate_runtime()` with:

```python
def validate_runtime(self) -> None:
    missing = []
    for path in (settings.upscale_engine_dir, settings.upscale_weights_dir):
        if not os.path.exists(path):
            missing.append(path)
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(
            "Upscale runtime assets are missing. Run `make setup-models` first:\n"
            f"{joined}"
        )

    available = get_available_upscale_backends(
        settings.upscale_engine_dir,
        settings.upscale_weights_dir,
    )
    if not available:
        raise FileNotFoundError(
            "No available upscale backends. Run `make setup-models` and verify "
            f"backend assets under {settings.upscale_engine_dir} and "
            f"{settings.upscale_weights_dir}."
        )
```

- [ ] **Step 5: Run engine tests**

Run:

```bash
rtk python -m pytest tests/test_engines.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
rtk git add app/engines/upscale.py tests/test_engines.py
rtk git commit -m "feat: validate available upscale backends at startup"
```

---

### Task 5: Convert RealESRGAN command to deterministic adapter path

**Files:**
- Modify: `app/upscaler.py`
- Modify: `tests/test_upscaler.py`
- Create: `third_party/Upscale/realesrgan/adapter.py`
- Create: `third_party/Upscale/realesrgan/vendor/.gitkeep`

- [ ] **Step 1: Update failing command expectation test**

Change `RealESRGANBackendTests.test_build_command_basic` in `tests/test_upscaler.py` so it expects `adapter.py`:

```python
def test_build_command_basic(self) -> None:
    cmd = self.backend.build_command(
        input_path="/input/video.mp4",
        output_dir="/output",
        engine_dir="/engines/upscale",
        weights_dir="/models/upscale",
        scale=2,
    )
    cmd_str = " ".join(cmd)
    self.assertIn("/engines/upscale/realesrgan/adapter.py", cmd_str)
    self.assertIn("-i", cmd_str)
    self.assertIn("/input/video.mp4", cmd_str)
    self.assertIn("-o", cmd_str)
    self.assertIn("/output", cmd_str)
    self.assertIn("-n", cmd_str)
    self.assertIn("realesr-animevideov3", cmd_str)
    self.assertIn("-s", cmd_str)
    self.assertIn("2", cmd_str)
    self.assertIn("--half", cmd_str)
```

- [ ] **Step 2: Run failing command test**

Run:

```bash
rtk python -m pytest tests/test_upscaler.py::RealESRGANBackendTests::test_build_command_basic -v
```

Expected: fail because `RealESRGANBackend` still builds the old bridge path.

- [ ] **Step 3: Update RealESRGAN command builder**

In `app/upscaler.py`, change `RealESRGANBackend.build_command()` script path to:

```python
script = container_join(engine_dir, "realesrgan", "adapter.py")
```

Keep the returned arguments the same:

```python
return [
    sys.executable,
    script,
    "-i",
    input_path,
    "-o",
    output_dir,
    "-n",
    "realesr-animevideov3",
    "-s",
    str(scale),
    "--half",
]
```

- [ ] **Step 4: Create deterministic RealESRGAN adapter**

Create `third_party/Upscale/realesrgan/adapter.py`:

```python
#!/usr/bin/env python3

from __future__ import annotations

import runpy
import sys
from pathlib import Path


_RUNNER = Path(__file__).resolve().parent / "vendor" / "inference_realesrgan_video.py"


def main() -> int:
    if not _RUNNER.is_file():
        sys.stderr.write(
            "RealESRGAN runner is missing. Expected vendored runner at "
            f"{_RUNNER}\n"
        )
        return 2

    original_argv = sys.argv[:]
    sys.argv = [str(_RUNNER), *original_argv[1:]]
    try:
        runpy.run_path(str(_RUNNER), run_name="__main__")
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 1
    finally:
        sys.argv = original_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `third_party/Upscale/realesrgan/vendor/.gitkeep` as an empty file.

- [ ] **Step 5: Run command and availability tests**

Run:

```bash
rtk python -m pytest tests/test_upscaler.py -v
```

Expected: pass, except availability tests should still require the vendor runner file in temp dirs.

- [ ] **Step 6: Commit**

```bash
rtk git add app/upscaler.py tests/test_upscaler.py third_party/Upscale/realesrgan/adapter.py third_party/Upscale/realesrgan/vendor/.gitkeep
rtk git commit -m "feat: use deterministic realesrgan adapter"
```

---

### Task 6: Update ModelSpec declarations for backend-level RealESRGAN assets

**Files:**
- Modify: `app/models/specs.py`
- Test: existing model spec tests, likely `tests/test_models.py` or `tests/test_model_manager.py`

- [ ] **Step 1: Locate model spec tests**

Run:

```bash
rtk grep "upscale-engine\|realesrgan-weights\|load_specs" tests
```

Expected: output shows the model spec test file and assertions to update.

- [ ] **Step 2: Update tests to expect backend-specific spec names**

In the located test file, replace expectations for:

```python
self.assertIn("upscale-engine", names)
self.assertIn("realesrgan-weights", names)
```

with:

```python
self.assertIn("upscale-realesrgan-engine", names)
self.assertIn("upscale-realesrgan-weights", names)
```

Update the engine spec assertion to:

```python
up_engine = next(s for s in specs if s.name == "upscale-realesrgan-engine")
self.assertEqual(up_engine.source_type, "submodule")
self.assertEqual(up_engine.target_dir, "/engines/upscale")
self.assertEqual(
    [f.path for f in up_engine.files],
    [
        "realesrgan/adapter.py",
        "realesrgan/vendor/inference_realesrgan_video.py",
    ],
)
```

Update the weight spec assertion to:

```python
weights = next(s for s in specs if s.name == "upscale-realesrgan-weights")
self.assertEqual(weights.source_type, "http")
self.assertEqual(
    weights.source_ref,
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
)
self.assertEqual(weights.target_dir, "/models/upscale/realesrgan")
self.assertEqual([f.path for f in weights.files], ["realesr-animevideov3.pth"])
self.assertTrue(weights.files[0].sha256)
```

- [ ] **Step 3: Run failing model spec tests**

Run the located test file, for example:

```bash
rtk python -m pytest tests/test_models.py -v
```

Expected: fail because `app/models/specs.py` still emits old spec names and bridge file.

- [ ] **Step 4: Update `app/models/specs.py`**

Replace the current `upscale-engine` spec with:

```python
ModelSpec(
    name="upscale-realesrgan-engine",
    source_type="submodule",
    source_ref="",
    target_dir=settings.upscale_engine_dir,
    files=[
        FileCheck(path="realesrgan/adapter.py"),
        FileCheck(path="realesrgan/vendor/inference_realesrgan_video.py"),
    ],
),
```

Replace the current `realesrgan-weights` spec with the same direct-artifact spec introduced in Task 1:

```python
ModelSpec(
    name="upscale-realesrgan-weights",
    source_type="http",
    source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
    target_dir=container_child(settings.upscale_weights_dir, "realesrgan"),
    files=[FileCheck(path="realesr-animevideov3.pth", sha256="<verified-sha256>")],
),
```

Use the verified digest from Task 1. Do not add a fake checksum.

- [ ] **Step 5: Run model spec tests**

Run:

```bash
rtk python -m pytest tests/test_models.py tests/test_settings.py -v
```

Expected: pass after using the actual model test filename found in Step 1.

- [ ] **Step 6: Commit**

```bash
rtk git add app/models/specs.py tests
rtk git commit -m "feat: declare backend-level realesrgan model specs"
```

---

### Task 7: Update documentation and remove stale bridge wording

**Files:**
- Modify: `third_party/Upscale/README.md`
- Modify: `docs/superpowers/plans/2026-04-25-model-download-manager.md`
- Modify: `docs/superpowers/specs/2026-04-25-model-download-manager-design.md`

- [ ] **Step 1: Update `third_party/Upscale/README.md`**

Replace the RealESRGAN launcher section with:

```markdown
## Backend contract

`third_party/Upscale` is the repository-managed engine bundle for `UpscaleEngine`.
Each backend owns a stable subdirectory under this bundle:

- `realesrgan/` — RealESRGAN adapter and vendored runner files
- `realbasicvsr/` — reserved for RealBasicVSR adapter/config/vendor files
- `seedvr2/` — reserved for SeedVR2 adapter/vendor files

At runtime the bundle is copied to `/engines/upscale`, while backend weights live under `/models/upscale/<backend>`.

## RealESRGAN

`realesrgan/adapter.py` is the stable entrypoint invoked by `app.upscaler.RealESRGANBackend`.
It deterministically delegates to `realesrgan/vendor/inference_realesrgan_video.py`.

A RealESRGAN backend is available only when both of these files exist under `/engines/upscale` and `realesrgan/realesr-animevideov3.pth` exists under `/models/upscale`.
```

- [ ] **Step 2: Fix stale plan path**

In `docs/superpowers/plans/2026-04-25-model-download-manager.md`, replace:

```bash
export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}/realesrgan}"
```

with:

```bash
export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}/upscale}"
```

- [ ] **Step 3: Fix stale spec wording**

In `docs/superpowers/specs/2026-04-25-model-download-manager-design.md`, replace:

```markdown
- RealBasicVSR and SeedVR2 backends: follow same `third_party/` pattern when ready, with their own engine_dirs and weights_dirs
```

with:

```markdown
- RealBasicVSR and SeedVR2 backends: follow the `third_party/Upscale/<backend>` pattern when ready, with assets under `upscale_engine_dir/<backend>` and `upscale_weights_dir/<backend>`
```

- [ ] **Step 4: Search for stale names**

Run:

```bash
rtk grep "MODEL_ROOT}/realesrgan\|third_party/RealESRGAN\|realesrgan_engine_dir\|REALESRGAN_ENGINE_DIR\|REALESRGAN_WEIGHTS_DIR" docs third_party app tests scripts Dockerfile docker-compose.yml
```

Expected: no active implementation references. Mentions in non-goals or superseded notes are acceptable only if they explicitly say the old names are superseded.

- [ ] **Step 5: Commit**

```bash
rtk git add third_party/Upscale/README.md docs/superpowers/plans/2026-04-25-model-download-manager.md docs/superpowers/specs/2026-04-25-model-download-manager-design.md
rtk git commit -m "docs: align upscale backend integration docs"
```

---

### Task 8: Run full verification and fix fallout

**Files:**
- Modify only files directly implicated by failing tests.

- [ ] **Step 1: Run targeted test suite**

Run:

```bash
rtk python -m pytest tests/test_upscaler.py tests/test_api.py tests/test_engines.py tests/test_settings.py -v
```

Expected: pass.

- [ ] **Step 2: Run model-manager tests**

Run the model spec test file found in Task 5:

```bash
rtk python -m pytest tests/test_models.py -v
```

If the file name differs, run that exact file instead.

Expected: pass.

- [ ] **Step 3: Run full test suite**

Run:

```bash
rtk python -m pytest -v
```

Expected: pass.

- [ ] **Step 4: Check working tree**

Run:

```bash
rtk git status --short
```

Expected: only intentional changes remain.

- [ ] **Step 5: Commit final fixes if any**

If Step 1-3 required additional changes, commit them:

```bash
rtk git add app tests docs third_party
rtk git commit -m "test: update upscale backend integration coverage"
```

If there were no additional changes after prior commits, skip this commit.

---

## Self-Review

### Spec coverage

- Direct RealESRGAN artifact provisioning: covered by Task 1.
- Directory contract: covered by Tasks 5 and 7.
- Backend metadata model: covered by Task 2.
- Registered vs available registry semantics: covered by Tasks 2 and 3.
- RealESRGAN deterministic adapter: covered by Task 5.
- ModelSpec backend-level declarations: covered by Tasks 1 and 6.
- API behavior: covered by Task 3.
- Worker runtime validation: covered by Task 4.
- Error handling: covered by Tasks 1, 3, and 4.
- Testing strategy: covered by Tasks 1, 2, 3, 4, 6, and 8.
- Documentation cleanup: covered by Task 7.

### Placeholder scan

The only implementation placeholder is `<verified-sha256>` in the RealESRGAN direct-artifact spec, and Task 1 requires replacing it with the digest computed from the official artifact before implementation is finalized. The plan intentionally avoids `sha256=None` for the production RealESRGAN weight.

### Type consistency

The plan consistently uses:

- `UpscaleBackendAssets`
- `assets`
- `get_available_upscale_backends(engine_dir, weights_dir, backends=UPSCALE_BACKENDS)`
- `upscale-realesrgan-engine`
- `upscale-realesrgan-weights`
- `third_party/Upscale/realesrgan/adapter.py`
- `source_type="http"`
- official Real-ESRGAN release artifact URL for `realesr-animevideov3.pth`
