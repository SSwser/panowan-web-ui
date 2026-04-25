# Upscale Backend Runtime Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend-specific runtime dependency isolation for UpscaleEngine so RealESRGAN can use its own pinned Python environment without polluting the PanoWan worker runtime, while flattening the vendor and weights directory structures for cleaner contracts.

**Architecture:** Keep `UPSCALE_BACKENDS` as the registered Python catalog and extend `UpscaleBackendAssets` with runtime Python and import-probe metadata. RealESRGAN executes through `/opt/venvs/upscale-realesrgan/bin/python -m realesrgan.vendor` (using `vendor/__main__.py` as entrypoint, replacing `adapter.py`). The vendored Real-ESRGAN source is directly under `vendor/` (no `Real-ESRGAN/` nesting). Weights live at `MODEL_ROOT/Real-ESRGAN/realesr-animevideov3.pth` (flat by model family, not by function). A backend is available only when files, weights, commands, venv Python, and required modules all validate. Docker builds the RealESRGAN venv at image build time from `third_party/Upscale/realesrgan/requirements.txt`; no runtime `pip install` is allowed.

**Tech Stack:** Python 3.12, unittest/pytest, Docker multi-stage builds, bash startup scripts, pinned backend `requirements.txt` files.

---

## File Structure

- Modify: `app/upscale_contract.py` — flatten vendor paths, flatten weight paths
- Modify: `app/upscaler.py` — update `build_command()` to use `vendor/__main__.py`, flatten weight paths
- Modify: `app/settings.py` — change `upscale_weights_dir` default from `MODEL_ROOT/upscale` to `MODEL_ROOT`
- Modify: `app/models/specs.py` — update engine file checks and weight target_dir
- Modify: `docker-compose.yml` — change `UPSCALE_WEIGHTS_DIR` from `/models/upscale` to `/models`
- Modify: `scripts/lib/env.sh` — change `UPSCALE_WEIGHTS_DIR` default from `${MODEL_ROOT}/upscale` to `${MODEL_ROOT}`
- Move: `third_party/Upscale/realesrgan/adapter.py` → `third_party/Upscale/realesrgan/vendor/__main__.py`
- Flatten: `third_party/Upscale/realesrgan/vendor/Real-ESRGAN/*` → `third_party/Upscale/realesrgan/vendor/*`
- Delete: `third_party/Upscale/realesrgan/vendor/inference_realesrgan_video.py` (old bridge copy)
- Modify: `Dockerfile` — already has venv stage (done), may need path adjustments
- Modify: `tests/test_upscaler.py` — update all path expectations
- Modify: `tests/test_models.py` — update engine file and weight path expectations
- Modify: `tests/test_scripts.py` — update adapter→__main__ test, add __main__.py contract tests

---

### Task 1: Flatten vendor directory and replace adapter.py with vendor/__main__.py

**Files:**
- Delete: `third_party/Upscale/realesrgan/adapter.py`
- Delete: `third_party/Upscale/realesrgan/vendor/inference_realesrgan_video.py` (old bridge copy)
- Move: `third_party/Upscale/realesrgan/vendor/Real-ESRGAN/inference_realesrgan_video.py` → `third_party/Upscale/realesrgan/vendor/inference_realesrgan_video.py`
- Move: `third_party/Upscale/realesrgan/vendor/Real-ESRGAN/realesrgan/` → `third_party/Upscale/realesrgan/vendor/realesrgan/`
- Delete: `third_party/Upscale/realesrgan/vendor/Real-ESRGAN/` (empty after moves)
- Create: `third_party/Upscale/realesrgan/vendor/__main__.py`
- Modify: `app/upscale_contract.py`
- Modify: `app/upscaler.py`

- [ ] **Step 1: Flatten vendor directory structure**

Move files to remove the `Real-ESRGAN/` nesting:

```
# From: vendor/Real-ESRGAN/inference_realesrgan_video.py
# To:   vendor/inference_realesrgan_video.py

# From: vendor/Real-ESRGAN/realesrgan/__init__.py
# To:   vendor/realesrgan/__init__.py

# From: vendor/Real-ESRGAN/realesrgan/utils.py
# To:   vendor/realesrgan/utils.py

# From: vendor/Real-ESRGAN/realesrgan/archs/__init__.py
# To:   vendor/realesrgan/archs/__init__.py

# From: vendor/Real-ESRGAN/realesrgan/archs/srvgg_arch.py
# To:   vendor/realesrgan/archs/srvgg_arch.py

# Delete: vendor/inference_realesrgan_video.py (old bridge copy)
# Delete: vendor/Real-ESRGAN/ (now empty)
# Delete: adapter.py (replaced by vendor/__main__.py)
```

After this, the vendor directory should be:

```
third_party/Upscale/realesrgan/vendor/
├── __main__.py
├── inference_realesrgan_video.py
└── realesrgan/
    ├── __init__.py
    ├── utils.py
    └── archs/
        ├── __init__.py
        └── srvgg_arch.py
```

- [ ] **Step 2: Create vendor/__main__.py**

Replace `adapter.py` with `vendor/__main__.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent


def main() -> int:
    runner = _VENDOR_DIR / "inference_realesrgan_video.py"
    if not runner.is_file():
        sys.stderr.write(
            "RealESRGAN runner is missing. Expected at "
            f"{runner}\n"
        )
        return 2

    sys.path.insert(0, str(_VENDOR_DIR))
    from inference_realesrgan_video import main as inference_main
    return inference_main() or 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Key differences from the old `adapter.py`:
- Uses direct import (`from inference_realesrgan_video import main as inference_main`) instead of `runpy.run_path()`
- Simpler — no argv/path save/restore because the venv Python process is isolated
- No `Real-ESRGAN/` nesting — `sys.path.insert(0, str(_VENDOR_DIR))` covers the flat layout

- [ ] **Step 3: Update `app/upscale_contract.py`**

Replace the entire file content with:

```python
"""Shared runtime contract constants for vendored upscale backends."""

REALESRGAN_ENGINE_FILES: tuple[str, ...] = (
    "realesrgan/vendor/__main__.py",
    "realesrgan/vendor/inference_realesrgan_video.py",
    "realesrgan/vendor/realesrgan/__init__.py",
    "realesrgan/vendor/realesrgan/utils.py",
    "realesrgan/vendor/realesrgan/archs/__init__.py",
    "realesrgan/vendor/realesrgan/archs/srvgg_arch.py",
)

REALESRGAN_WEIGHT_FILES: tuple[str, ...] = ("Real-ESRGAN/realesr-animevideov3.pth",)

REALESRGAN_REQUIRED_COMMANDS: tuple[str, ...] = ("ffmpeg",)

REALESRGAN_RUNTIME_PYTHON = "/opt/venvs/upscale-realesrgan/bin/python"

# These are the modules installed into the backend venv itself. The vendored
# `realesrgan` package is validated via the required engine files above.
REALESRGAN_RUNTIME_MODULES: tuple[str, ...] = ("cv2", "ffmpeg", "tqdm")
```

Changes:
- `realesrgan/adapter.py` → `realesrgan/vendor/__main__.py`
- All `realesrgan/vendor/Real-ESRGAN/` → `realesrgan/vendor/`
- `realesrgan/realesr-animevideov3.pth` → `Real-ESRGAN/realesr-animevideov3.pth`

- [ ] **Step 4: Update `app/upscaler.py` `RealESRGANBackend.build_command()`**

Change the `build_command` method:

```python
    def build_command(
        self,
        input_path: str,
        output_dir: str,
        engine_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        vendor_dir = container_join(engine_dir, "realesrgan", "vendor")
        model_path = container_join(
            weights_dir, "Real-ESRGAN", "realesr-animevideov3.pth"
        )
        return [
            self.assets.runtime_python or sys.executable,
            "-m",
            "realesrgan.vendor",
            "-i",
            input_path,
            "-o",
            output_dir,
            "-n",
            "realesr-animevideov3",
            "--model_path",
            model_path,
            "-s",
            str(scale),
        ]
```

Changes:
- Uses `python -m realesrgan.vendor` instead of `python <adapter.py path>` — this invokes `vendor/__main__.py`
- Weight path: `Real-ESRGAN/realesr-animevideov3.pth` instead of `realesrgan/realesr-animevideov3.pth`
- Note: `-m realesrgan.vendor` only works when `realesrgan/` is on `sys.path` — need to add the engine dir's `realesrgan` parent to PYTHONPATH. Since the command runs in the backend venv, the adapter can set `sys.path` internally. Alternatively, add `PYTHONPATH` env var. The simplest approach: use the absolute path to `__main__.py` directly.

Actually, let's keep it simple and just run the `__main__.py` directly:

```python
    def build_command(
        self,
        input_path: str,
        output_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        script = container_join(engine_dir, "realesrgan", "vendor", "__main__.py")
        model_path = container_join(
            weights_dir, "Real-ESRGAN", "realesr-animevideov3.pth"
        )
        return [
            self.assets.runtime_python or sys.executable,
            script,
            "-i",
            input_path,
            "-o",
            output_dir,
            "-n",
            "realesr-animevideov3",
            "--model_path",
            model_path,
            "-s",
            str(scale),
        ]
```

This is the most straightforward approach: the venv Python runs `__main__.py` directly, which handles `sys.path` setup internally.

- [ ] **Step 5: Commit**

```bash
rtk git add -A third_party/Upscale/realesrgan/ app/upscale_contract.py app/upscaler.py
rtk git commit -m "refactor: flatten vendor dir and replace adapter.py with vendor/__main__.py"
```

---

### Task 2: Flatten weights directory to MODEL_ROOT/<ModelFamily>

**Files:**
- Modify: `app/settings.py`
- Modify: `docker-compose.yml`
- Modify: `scripts/lib/env.sh`
- Modify: `app/models/specs.py`

- [ ] **Step 1: Update `app/settings.py` default for `upscale_weights_dir`**

Change:
```python
        upscale_weights_dir=os.getenv(
            "UPSCALE_WEIGHTS_DIR", container_child(model_root, "upscale")
        ),
```
to:
```python
        upscale_weights_dir=os.getenv(
            "UPSCALE_WEIGHTS_DIR", model_root
        ),
```

Rationale: Weights are organized by model family (`Real-ESRGAN/`, `RealBasicVSR/`, etc.) directly under `MODEL_ROOT`, not grouped under a functional `upscale/` subdirectory. This mirrors how generation models are stored (`Wan-AI/Wan2.1-T2V-1.3B/` is directly under `MODEL_ROOT`).

- [ ] **Step 2: Update `docker-compose.yml`**

Change `UPSCALE_WEIGHTS_DIR: /models/upscale` to `UPSCALE_WEIGHTS_DIR: /models` in both `worker-panowan` and `model-setup` services.

- [ ] **Step 3: Update `scripts/lib/env.sh`**

Change:
```bash
  export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}/upscale}"
```
to:
```bash
  export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}}"
```

- [ ] **Step 4: Update `app/models/specs.py` weight target_dir**

Change the `upscale-realesrgan-weights` spec:
```python
        ModelSpec(
            name="upscale-realesrgan-weights",
            source_type="http",
            source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
            target_dir=container_child(settings.upscale_weights_dir, "Real-ESRGAN"),
            files=[
                FileCheck(
                    path="realesr-animevideov3.pth",
                    sha256="b8a8376811077954d82ca3fcf476f1ac3da3e8a68a4f4d71363008000a18b75d",
                )
            ],
        ),
```

Changed: `container_child(settings.upscale_weights_dir, "realesrgan")` → `container_child(settings.upscale_weights_dir, "Real-ESRGAN")`.

With `upscale_weights_dir` now defaulting to `/models`, the final weight path becomes `/models/Real-ESRGAN/realesr-animevideov3.pth`.

- [ ] **Step 5: Commit**

```bash
rtk git add app/settings.py docker-compose.yml scripts/lib/env.sh app/models/specs.py
rtk git commit -m "refactor: flatten weights dir to MODEL_ROOT/<ModelFamily>"
```

---

### Task 3: Update all tests for flattened paths

**Files:**
- Modify: `tests/test_upscaler.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_scripts.py`

- [ ] **Step 1: Update `tests/test_upscaler.py`**

Key changes:
1. `_materialize_backend_assets` already reads from `backend.assets.engine_files` and `backend.assets.weight_files`, so it auto-adapts to the new paths in `upscale_contract.py`
2. `test_backend_unavailable_when_engine_file_missing`: weight path changes from `realesrgan/realesr-animevideov3.pth` to `Real-ESRGAN/realesr-animevideov3.pth`
3. `test_build_command_basic`: assert `adapter.py` → assert `vendor/__main__.py`, weight path changes
4. Runtime probe assertions: `import cv2; import ffmpeg; import tqdm` (not `import basicsr; import realesrgan` — those are validated via engine files, not runtime modules)

In `test_backend_unavailable_when_engine_file_missing`, change:
```python
            Path(weights_dir, "realesrgan").mkdir(parents=True)
            Path(weights_dir, "realesrgan", "realesr-animevideov3.pth").write_text("x")
```
to:
```python
            Path(weights_dir, "Real-ESRGAN").mkdir(parents=True)
            Path(weights_dir, "Real-ESRGAN", "realesr-animevideov3.pth").write_text("x")
```

In `test_build_command_basic`, change:
```python
        self.assertIn("/engines/upscale/realesrgan/adapter.py", cmd_str)
```
to:
```python
        self.assertIn("/engines/upscale/realesrgan/vendor/__main__.py", cmd_str)
```

And change:
```python
        self.assertIn(
            "/models/upscale/realesrgan/realesr-animevideov3.pth",
            cmd_str,
        )
```
to:
```python
        self.assertIn(
            "/models/Real-ESRGAN/realesr-animevideov3.pth",
            cmd_str,
        )
```

- [ ] **Step 2: Update `tests/test_models.py`**

In `test_upscale_engine_spec_is_submodule_type`, change the expected files:
```python
        self.assertEqual(
            re_engine.files,
            [
                FileCheck(path="realesrgan/vendor/__main__.py"),
                FileCheck(path="realesrgan/vendor/inference_realesrgan_video.py"),
                FileCheck(path="realesrgan/vendor/realesrgan/__init__.py"),
                FileCheck(path="realesrgan/vendor/realesrgan/utils.py"),
                FileCheck(path="realesrgan/vendor/realesrgan/archs/__init__.py"),
                FileCheck(path="realesrgan/vendor/realesrgan/archs/srvgg_arch.py"),
            ],
        )
```

In `test_upscale_realesrgan_weights_spec_uses_official_http_artifact`, change:
```python
        self.assertEqual(weights.target_dir, "/models/Real-ESRGAN")
```

And update the `env` dict in both tests:
```python
            "UPSCALE_WEIGHTS_DIR": "/models",
```

- [ ] **Step 3: Update `tests/test_scripts.py`**

Replace `test_realesrgan_adapter_uses_vendored_snapshot_without_runtime_pip` with:

```python
    def test_realesrgan_main_uses_vendored_runner_without_runtime_pip(self):
        main_py = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "vendor" / "__main__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"inference_realesrgan_video.py"', main_py)
        self.assertIn("sys.path.insert", main_py)
        self.assertNotIn("pip.main", main_py)
        self.assertNotIn("pip install", main_py)
        self.assertNotIn("adapter", main_py)
```

Update `test_realesrgan_runtime_bundle_does_not_require_basicsr_package` — change all paths from `vendor/Real-ESRGAN/` to `vendor/`:

```python
    def test_realesrgan_runtime_bundle_does_not_require_basicsr_package(self):
        requirements = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "requirements.txt"
        ).read_text(encoding="utf-8")
        runner = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "inference_realesrgan_video.py"
        ).read_text(encoding="utf-8")
        utils = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "realesrgan"
            / "utils.py"
        ).read_text(encoding="utf-8")
        arch = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "realesrgan"
            / "archs"
            / "srvgg_arch.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("basicsr", requirements)
        self.assertNotIn("from basicsr", runner)
        self.assertIn("GFPGANer = None", runner)
        self.assertNotIn("load_file_from_url", utils)
        self.assertNotIn("ARCH_REGISTRY", arch)
```

Update `test_realesrgan_runtime_package_inits_are_trimmed` — change paths:

```python
    def test_realesrgan_runtime_package_inits_are_trimmed(self):
        package_init = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "realesrgan"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        arch_init = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "realesrgan"
            / "archs"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from .utils import RealESRGANer", package_init)
        self.assertNotIn("from .data", package_init)
        self.assertNotIn("from .models", package_init)
        self.assertNotIn("from .version", package_init)
        self.assertEqual(
            arch_init.strip(),
            'from .srvgg_arch import SRVGGNetCompact\n\n__all__ = ["SRVGGNetCompact"]',
        )
```

Update `test_realesrgan_runner_only_exposes_supported_cli_surface` — change path:

```python
    def test_realesrgan_runner_only_exposes_supported_cli_surface(self):
        runner = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "inference_realesrgan_video.py"
        ).read_text(encoding="utf-8")
        self.assertIn('default="realesr-animevideov3"', runner)
        self.assertNotIn("RealESRGAN_x4plus", runner)
        self.assertNotIn("--denoise_strength", runner)
        self.assertNotIn("--alpha_upsampler", runner)
        self.assertNotIn('"--ext",', runner)
```

- [ ] **Step 4: Commit**

```bash
rtk git add tests/test_upscaler.py tests/test_models.py tests/test_scripts.py
rtk git commit -m "test: update paths for flattened vendor and weights dirs"
```

---

### Task 4: Tighten realesrgan runtime contract

**Files:**
- Modify: `third_party/Upscale/realesrgan/vendor/inference_realesrgan_video.py`
- Modify: `third_party/Upscale/realesrgan/requirements.txt`

- [ ] **Step 1: Verify vendored runner doesn't import basicsr**

The vendored `inference_realesrgan_video.py` at `vendor/Real-ESRGAN/inference_realesrgan_video.py` currently imports `from basicsr.archs.rrdbnet_arch import RRDBNet` and `from basicsr.utils.download_util import load_file_from_url`. These must be removed in the flattened copy since `basicsr` is not in `requirements.txt`.

The test `test_realesrgan_runtime_bundle_does_not_require_basicsr_package` already validates this. After flattening, verify the vendored copy has these stripped.

If the existing vendored copy at `vendor/Real-ESRGAN/` already has these stripped (per the `test_realesrgan_runtime_bundle_does_not_require_basicsr_package` test which checks `assertNotIn("from basicsr", runner)` and `assertIn("GFPGANer = None", runner)`), then this step is already done.

- [ ] **Step 2: Verify requirements.txt is correct**

Current `requirements.txt`:
```
basicsr==1.4.2
ffmpeg-python==0.2.0
opencv-python-headless==4.10.0.84
tqdm==4.67.1
```

But the test `test_realesrgan_runtime_bundle_does_not_require_basicsr_package` asserts `self.assertNotIn("basicsr", requirements)`. This is a contradiction — if the vendored runner doesn't import `basicsr`, we shouldn't install it.

Resolution: Remove `basicsr` from `requirements.txt` since the vendored runner has been trimmed to not depend on it. The trimmed runner only needs `cv2`, `ffmpeg`, `tqdm`, `torch`, and the vendored `realesrgan` package (which is on `sys.path` via `__main__.py`).

Update `requirements.txt` to:
```
ffmpeg-python==0.2.0
opencv-python-headless==4.10.0.84
tqdm==4.67.1
```

- [ ] **Step 3: Commit**

```bash
rtk git add third_party/Upscale/realesrgan/requirements.txt
rtk git commit -m "refactor: remove basicsr from realesrgan requirements (vendored runner is trimmed)"
```

---

### Task 5: Update documentation and focused spec

**Files:**
- Modify: `third_party/Upscale/README.md`
- Modify: `docs/superpowers/specs/2026-04-25-upscale-backend-integration-design.md`

- [ ] **Step 1: Update README with flattened structure**

Update `third_party/Upscale/README.md` to reflect:
- `vendor/__main__.py` entrypoint (not `adapter.py`)
- Flat vendor directory (no `Real-ESRGAN/` nesting)
- Flat weights directory (`MODEL_ROOT/Real-ESRGAN/` not `MODEL_ROOT/upscale/realesrgan/`)
- Backend runtime isolation with per-backend venv

- [ ] **Step 2: Update focused spec**

Update `docs/superpowers/specs/2026-04-25-upscale-backend-integration-design.md` with:
- New vendor file list (flattened)
- New weight path (`Real-ESRGAN/realesr-animevideov3.pth`)
- `__main__.py` entrypoint contract instead of `adapter.py`
- Updated `UpscaleBackendAssets` with `runtime_python` and `required_python_modules`

- [ ] **Step 3: Commit**

```bash
rtk git add third_party/Upscale/README.md docs/superpowers/specs/2026-04-25-upscale-backend-integration-design.md
rtk git commit -m "docs: update spec and README for flattened vendor/weights structure"
```

---

### Task 6: Run full verification

**Files:**
- Modify only files directly implicated by failing tests.

- [ ] **Step 1: Run targeted tests**

```bash
rtk python -m pytest tests/test_upscaler.py tests/test_models.py tests/test_scripts.py -v
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

```bash
rtk python -m pytest -v
```

Expected: pass.

- [ ] **Step 3: Verify Dockerfile still builds correctly**

The Dockerfile already has the `upscale-realesrgan-deps` stage and venv copy. Verify no path changes broke it:

```bash
rtk docker build --target worker-panowan -t panowan-worker:runtime-isolation .
```

Expected: image builds successfully.

- [ ] **Step 4: Check working tree**

```bash
rtk git status --short
```

Expected: only intentional changes remain.

---

## Self-Review

### Spec coverage

- Vendor directory flattening (`Real-ESRGAN/` → flat): covered by Task 1
- `adapter.py` → `vendor/__main__.py`: covered by Task 1
- Weights directory flattening (`/models/upscale/realesrgan/` → `/models/Real-ESRGAN/`): covered by Task 2
- `UPSCALE_WEIGHTS_DIR` default change: covered by Task 2
- `build_command()` path updates: covered by Task 1
- `upscale_contract.py` path updates: covered by Task 1
- All test updates: covered by Task 3
- Runtime contract tightening (no basicsr): covered by Task 4
- Documentation: covered by Task 5
- Verification: covered by Task 6

### What's already done (from previous sessions)

These items are already implemented and NOT repeated in this plan:
- `UpscaleBackendAssets` with `runtime_python` and `required_python_modules` — already in `app/upscaler.py`
- `_has_backend_runtime()` probe — already in `app/upscaler.py`
- `get_available_upscale_backends()` with runtime probe — already in `app/upscaler.py`
- Docker `upscale-realesrgan-deps` stage with `--system-site-packages` venv — already in `Dockerfile`
- `ffmpeg` and `python3-venv` in `runtime-base` — already in `Dockerfile`
- `COPY --from=upscale-realesrgan-deps` in worker stages — already in `Dockerfile`
- `HttpProvider` for weight downloads — already in `app/models/providers.py`
- Availability gating in API endpoints — already implemented

### Type consistency

The plan consistently uses:
- `realesrgan/vendor/__main__.py` (not `adapter.py`)
- `realesrgan/vendor/inference_realesrgan_video.py` (not `vendor/Real-ESRGAN/...`)
- `realesrgan/vendor/realesrgan/` (not `vendor/Real-ESRGAN/realesrgan/`)
- `Real-ESRGAN/realesr-animevideov3.pth` (not `realesrgan/realesr-animevideov3.pth`)
- `MODEL_ROOT` as default for `upscale_weights_dir` (not `MODEL_ROOT/upscale`)
- `/models/Real-ESRGAN/` as container weight path (not `/models/upscale/realesrgan/`)
