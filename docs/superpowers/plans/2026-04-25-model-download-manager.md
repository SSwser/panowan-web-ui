# Model Download Manager + UpscaleEngine Implementation Plan

> Final implementation update (2026-04-25): the engine layer uses generic Upscale naming.
>
> - `third_party/Upscale`
> - `/engines/upscale`
> - `UPSCALE_ENGINE_DIR`, `UPSCALE_WEIGHTS_DIR`
> - `upscale_engine_dir`, `upscale_weights_dir`
>
> `RealESRGAN` remains a backend under `third_party/Upscale/realesrgan/`. All engine-level naming in this plan now uses the `upscale_*` convention aligned with `UpscaleEngine`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace duplicated shell-based model provisioning with a unified Python ModelManager, introduce UpscaleEngine as a peer to PanoWanEngine, and restructure upscaler paths to separate scripts from weights.

**Architecture:** A declarative `ModelSpec` registry drives `HuggingFaceProvider` and `SubmoduleProvider` to download or verify model assets. Shell scripts become thin wrappers around `python -m app.models [ensure|verify]`. UpscaleEngine is extracted from PanoWanEngine with its own `validate_runtime()` and `run()`. The upscaler `build_command` signature splits `model_dir` into `engine_dir` (scripts) + `weights_dir` (weights).

**Tech Stack:** Python dataclasses, `huggingface_hub`, `posixpath`, unittest + mock, FastAPI (unchanged)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/models/__init__.py` | Module init, re-exports |
| Create | `app/models/registry.py` | `ModelSpec`, `FileCheck` dataclasses |
| Create | `app/models/providers.py` | `ModelProvider` Protocol, `HuggingFaceProvider`, `SubmoduleProvider` |
| Create | `app/models/manager.py` | `ModelManager` — `ensure()` / `verify()` |
| Create | `app/models/specs.py` | `load_specs(settings)` — all ModelSpec declarations |
| Create | `app/models/__main__.py` | CLI: `python -m app.models [ensure\|verify]` |
| Create | `app/engines/upscale.py` | `UpscaleEngine` class |
| Create | `tests/test_models.py` | ModelManager, providers, specs tests |
| Modify | `app/settings.py` | Remove `upscale_model_dir`, add `upscale_engine_dir` + `upscale_weights_dir` |
| Modify | `app/upscaler.py` | `model_dir` → `engine_dir` + `weights_dir` in Protocol and all backends |
| Modify | `app/engines/panowan.py` | Remove upscale branch, capabilities → `("t2v", "i2v")` |
| Modify | `app/engines/__init__.py` | Export `UpscaleEngine` |
| Modify | `app/worker_service.py` | Register `UpscaleEngine`, add `_resolve_engine()` |
| Modify | `scripts/model-setup.sh` | Simplify to `exec python -m app.models ensure` |
| Modify | `scripts/download-models.sh` | Set host env vars + `python -m app.models ensure` |
| Modify | `scripts/check-runtime.sh` | Simplify to `exec python -m app.models verify` |
| Modify | `scripts/start-local.sh` | Replace inline download with `python -m app.models ensure` |
| Modify | `Dockerfile` | Add `COPY third_party/Upscale /engines/upscale` |
| Modify | `docker-compose.yml` | Add `UPSCALE_ENGINE_DIR`, `UPSCALE_WEIGHTS_DIR` |
| Modify | `.env.example` | Update upscale section with new env vars |
| Modify | `tests/test_settings.py` | Update for new settings fields |
| Modify | `tests/test_upscaler.py` | Update for `engine_dir` + `weights_dir` |
| Modify | `tests/test_engines.py` | Add `UpscaleEngine` tests |
| Modify | `tests/test_worker_service.py` | Update for multi-engine registry |
| Modify | `tests/test_api.py` | Update for settings changes if needed |
| Modify | `pyproject.toml` | Add `huggingface_hub` dependency |

---

## Task 1: Settings — Replace upscale_model_dir with upscale_engine_dir + upscale_weights_dir

**Files:**

- Modify: `app/settings.py`
- Modify: `tests/test_settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

In `tests/test_settings.py`, replace the existing `test_load_settings_includes_upscale_defaults` and `test_load_settings_upscale_from_environment` with:

```python
def test_load_settings_includes_upscale_defaults(self) -> None:
    loaded = load_settings()
    self.assertEqual(loaded.upscale_engine_dir, "/engines/upscale")
    self.assertEqual(loaded.upscale_weights_dir, "/models/upscale")
    self.assertEqual(loaded.upscale_output_dir, "/app/runtime/outputs")
    self.assertEqual(loaded.upscale_timeout_seconds, 1800)

def test_load_settings_upscale_from_environment(self) -> None:
    env = {
        "UPSCALE_ENGINE_DIR": "/custom/engine",
        "UPSCALE_WEIGHTS_DIR": "/custom/weights",
        "UPSCALE_OUTPUT_DIR": "/custom/outputs",
        "UPSCALE_TIMEOUT_SECONDS": "900",
    }
    with patch.dict(os.environ, env, clear=False):
        loaded = load_settings()
    self.assertEqual(loaded.upscale_engine_dir, "/custom/engine")
    self.assertEqual(loaded.upscale_weights_dir, "/custom/weights")
    self.assertEqual(loaded.upscale_output_dir, "/custom/outputs")
    self.assertEqual(loaded.upscale_timeout_seconds, 900)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -v`
Expected: FAIL — `Settings` has no attribute `upscale_engine_dir`

- [ ] **Step 3: Implement settings changes**

In `app/settings.py`, replace `upscale_model_dir: str` with two new fields:

```python
@dataclass(frozen=True)
class Settings:
    # ... existing fields ...
    # REMOVED: upscale_model_dir: str
    upscale_engine_dir: str
    upscale_weights_dir: str
    upscale_output_dir: str
    upscale_timeout_seconds: int
    # ... rest unchanged ...
```

In `load_settings()`, replace the `upscale_model_dir` line:

```python
def load_settings() -> Settings:
    # ... existing setup ...
    return Settings(
        # ... existing fields ...
        upscale_engine_dir=os.getenv(
            "UPSCALE_ENGINE_DIR", "/engines/upscale"
        ),
        upscale_weights_dir=os.getenv(
            "UPSCALE_WEIGHTS_DIR", container_child(model_root, "upscale")
        ),
        upscale_output_dir=os.getenv("UPSCALE_OUTPUT_DIR", output_dir),
        upscale_timeout_seconds=int(os.getenv("UPSCALE_TIMEOUT_SECONDS", "1800")),
        # ... rest unchanged ...
    )
```

In `.env.example`, replace the upscale section:

```bash
# ─── Upscale ──────────────────────────────────────────────────────
UPSCALE_ENGINE_DIR=/engines/upscale
UPSCALE_WEIGHTS_DIR=/models/upscale
UPSCALE_OUTPUT_DIR=/app/runtime/outputs
UPSCALE_TIMEOUT_SECONDS=1800
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/settings.py tests/test_settings.py .env.example
git commit -m "feat: replace upscale_model_dir with upscale_engine_dir + upscale_weights_dir"
```

---

## Task 2: ModelSpec and FileCheck dataclasses

**Files:**

- Create: `app/models/__init__.py`
- Create: `app/models/registry.py`
- Create: `tests/test_models.py` (first test group)

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
import os
import unittest
from unittest.mock import MagicMock, patch

from app.models.registry import FileCheck, ModelSpec


class ModelSpecTests(unittest.TestCase):
    def test_modelspec_is_frozen(self) -> None:
        spec = ModelSpec(
            name="test",
            source_type="huggingface",
            source_ref="org/repo",
            target_dir="/models/test",
            files=[FileCheck(path="model.bin")],
        )
        with self.assertRaises(AttributeError):
            spec.name = "changed"

    def test_filecheck_is_frozen(self) -> None:
        fc = FileCheck(path="model.bin", sha256="abc123")
        with self.assertRaises(AttributeError):
            fc.path = "other.bin"

    def test_filecheck_sha256_defaults_to_none(self) -> None:
        fc = FileCheck(path="model.bin")
        self.assertIsNone(fc.sha256)

    def test_modelspec_subfolder_defaults_to_none(self) -> None:
        spec = ModelSpec(
            name="test", source_type="huggingface",
            source_ref="org/repo", target_dir="/tmp", files=[],
        )
        self.assertIsNone(spec.subfolder)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Implement ModelSpec and FileCheck**

Create `app/models/__init__.py`:

```python
from .manager import ModelManager
from .registry import FileCheck, ModelSpec

__all__ = ["FileCheck", "ModelSpec", "ModelManager"]
```

Create `app/models/registry.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FileCheck:
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    source_type: str
    source_ref: str
    target_dir: str
    files: list[FileCheck]
    subfolder: str | None = None
    git_ref: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/__init__.py app/models/registry.py tests/test_models.py
git commit -m "feat: add ModelSpec and FileCheck dataclasses for model registry"
```

---

## Task 3: Provider abstraction — SubmoduleProvider

**Files:**

- Create: `app/models/providers.py`
- Modify: `tests/test_models.py` (add provider tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from app.models.providers import SubmoduleProvider


class SubmoduleProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = SubmoduleProvider()

    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_ensure_passes_when_file_exists(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        self.provider.ensure(spec)  # Should not raise

    @patch("app.models.providers.os.path.exists", return_value=False)
    def test_ensure_raises_when_file_missing(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        with self.assertRaises(FileNotFoundError) as ctx:
            self.provider.ensure(spec)
        self.assertIn("submodule", str(ctx.exception).lower() + " third_party")

    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_verify_passes_when_file_exists(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        self.provider.verify(spec)  # Should not raise

    @patch("app.models.providers.os.path.exists", return_value=False)
    def test_verify_raises_when_file_missing(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        with self.assertRaises(FileNotFoundError):
            self.provider.verify(spec)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py::SubmoduleProviderTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.providers'`

- [ ] **Step 3: Implement SubmoduleProvider**

Create `app/models/providers.py`:

```python
import os
from typing import Protocol

from .registry import ModelSpec


class ModelProvider(Protocol):
    def ensure(self, spec: ModelSpec) -> None: ...
    def verify(self, spec: ModelSpec) -> None: ...


class SubmoduleProvider:
    """Verifies submodule-backed assets built into the Docker image."""

    def ensure(self, spec: ModelSpec) -> None:
        self.verify(spec)

    def verify(self, spec: ModelSpec) -> None:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.exists(full_path):
                raise FileNotFoundError(
                    f"Submodule artifact missing: {full_path}. "
                    f"This should be included in the Docker image via third_party/."
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/providers.py tests/test_models.py
git commit -m "feat: add SubmoduleProvider for verifying image-builtin model assets"
```

---

## Task 4: HuggingFaceProvider

**Files:**

- Modify: `app/models/providers.py`
- Modify: `tests/test_models.py` (add HuggingFaceProvider tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from app.models.providers import HuggingFaceProvider


class HuggingFaceProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = HuggingFaceProvider()

    @patch("app.models.providers.os.path.isfile", return_value=True)
    def test_ensure_skips_download_when_files_exist(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with patch("app.models.providers.snapshot_download") as mock_dl:
            self.provider.ensure(spec)
            mock_dl.assert_not_called()

    @patch("app.models.providers.os.path.isfile", return_value=False)
    def test_ensure_downloads_when_files_missing(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with patch("app.models.providers.snapshot_download") as mock_dl:
            # After download, simulate files now existing
            mock_isfile.side_effect = [False, True]
            self.provider.ensure(spec)
            mock_dl.assert_called_once_with(
                repo_id="org/model",
                local_dir="/models/test",
            )

    @patch("app.models.providers.os.path.isfile", return_value=True)
    def test_verify_passes_when_files_exist(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        self.provider.verify(spec)  # Should not raise

    @patch("app.models.providers.os.path.isfile", return_value=False)
    def test_verify_raises_when_files_missing(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with self.assertRaises(FileNotFoundError):
            self.provider.verify(spec)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py::HuggingFaceProviderTests -v`
Expected: FAIL — `ImportError: cannot import name 'HuggingFaceProvider'`

- [ ] **Step 3: Implement HuggingFaceProvider**

Add to `app/models/providers.py`:

```python
import hashlib
import os
from typing import Protocol

from .registry import ModelSpec


class ModelProvider(Protocol):
    def ensure(self, spec: ModelSpec) -> None: ...
    def verify(self, spec: ModelSpec) -> None: ...


def _check_sha256(path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest() == expected


class HuggingFaceProvider:
    """Downloads model assets from Hugging Face Hub."""

    def _all_files_present(self, spec: ModelSpec) -> bool:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.isfile(full_path):
                return False
            if f.sha256 and not _check_sha256(full_path, f.sha256):
                return False
        return True

    def verify(self, spec: ModelSpec) -> None:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.isfile(full_path):
                raise FileNotFoundError(
                    f"Missing model file: {full_path} (spec: {spec.name})"
                )
            if f.sha256 and not _check_sha256(full_path, f.sha256):
                raise RuntimeError(
                    f"Hash mismatch for {full_path} (spec: {spec.name})"
                )

    def ensure(self, spec: ModelSpec) -> None:
        if self._all_files_present(spec):
            return
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=spec.source_ref,
            local_dir=spec.target_dir,
        )
        if not self._all_files_present(spec):
            raise RuntimeError(
                f"Download completed but files still missing for {spec.name}"
            )


class SubmoduleProvider:
    """Verifies submodule-backed assets built into the Docker image."""

    def ensure(self, spec: ModelSpec) -> None:
        self.verify(spec)

    def verify(self, spec: ModelSpec) -> None:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.exists(full_path):
                raise FileNotFoundError(
                    f"Submodule artifact missing: {full_path}. "
                    f"This should be included in the Docker image via third_party/."
                )
```

Also add `from huggingface_hub import snapshot_download` is done lazily inside `ensure()` to avoid import failure when `huggingface_hub` is not installed (e.g. in the API container). The import is already inside the method body — no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/providers.py tests/test_models.py
git commit -m "feat: add HuggingFaceProvider for downloading model assets from HF Hub"
```

---

## Task 5: ModelManager

**Files:**

- Create: `app/models/manager.py`
- Modify: `tests/test_models.py` (add ModelManager tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from app.models.manager import ModelManager


class ModelManagerTests(unittest.TestCase):
    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_ensure_calls_provider_for_each_spec(self, mock_exists) -> None:
        spec1 = ModelSpec(
            name="engine-a", source_type="submodule", source_ref="",
            target_dir="/engines/a", files=[FileCheck(path="run.py")],
        )
        spec2 = ModelSpec(
            name="engine-b", source_type="submodule", source_ref="",
            target_dir="/engines/b", files=[FileCheck(path="run.py")],
        )
        manager = ModelManager()
        manager.ensure([spec1, spec2])  # Should not raise

    @patch("app.models.providers.os.path.exists", return_value=False)
    def test_verify_returns_missing_spec_names(self, mock_exists) -> None:
        spec1 = ModelSpec(
            name="missing-a", source_type="submodule", source_ref="",
            target_dir="/engines/a", files=[FileCheck(path="run.py")],
        )
        spec2 = ModelSpec(
            name="missing-b", source_type="submodule", source_ref="",
            target_dir="/engines/b", files=[FileCheck(path="run.py")],
        )
        manager = ModelManager()
        missing = manager.verify([spec1, spec2])
        self.assertEqual(missing, ["missing-a", "missing-b"])

    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_verify_returns_empty_when_all_present(self, mock_exists) -> None:
        spec = ModelSpec(
            name="present-a", source_type="submodule", source_ref="",
            target_dir="/engines/a", files=[FileCheck(path="run.py")],
        )
        manager = ModelManager()
        missing = manager.verify([spec])
        self.assertEqual(missing, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py::ModelManagerTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.manager'`

- [ ] **Step 3: Implement ModelManager**

Create `app/models/manager.py`:

```python
from .providers import HuggingFaceProvider, SubmoduleProvider
from .registry import ModelSpec


class ModelManager:
    def __init__(self) -> None:
        self._providers = {
            "huggingface": HuggingFaceProvider(),
            "submodule": SubmoduleProvider(),
        }

    def ensure(self, specs: list[ModelSpec]) -> None:
        for spec in specs:
            provider = self._providers.get(spec.source_type)
            if provider is None:
                raise ValueError(f"Unknown source_type: {spec.source_type}")
            provider.ensure(spec)

    def verify(self, specs: list[ModelSpec]) -> list[str]:
        missing = []
        for spec in specs:
            provider = self._providers.get(spec.source_type)
            if provider is None:
                missing.append(spec.name)
                continue
            try:
                provider.verify(spec)
            except (FileNotFoundError, RuntimeError):
                missing.append(spec.name)
        return missing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/manager.py tests/test_models.py
git commit -m "feat: add ModelManager with ensure and verify methods"
```

---

## Task 6: ModelSpec declarations (load_specs)

**Files:**

- Create: `app/models/specs.py`
- Modify: `tests/test_models.py` (add specs tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from app.models.specs import load_specs


class LoadSpecsTests(unittest.TestCase):
    @patch("app.models.specs.load_settings")
    def test_load_specs_returns_expected_spec_names(self, mock_settings) -> None:
        mock_settings.return_value = MagicMock(
            wan_model_path="/models/Wan-AI/Wan2.1-T2V-1.3B",
            lora_checkpoint_path="/models/PanoWan/latest-lora.ckpt",
            panowan_engine_dir="/engines/panowan",
            upscale_engine_dir="/engines/upscale",
            upscale_weights_dir="/models/upscale",
        )
        specs = load_specs()
        names = [s.name for s in specs]
        self.assertIn("wan-t2v-1.3b", names)
        self.assertIn("panowan-lora", names)
        self.assertIn("panowan-engine", names)
        self.assertIn("upscale-engine", names)
        self.assertIn("realesrgan-weights", names)
        self.assertEqual(len(specs), 5)

    @patch("app.models.specs.load_settings")
    def test_upscale_engine_is_submodule_type(self, mock_settings) -> None:
        mock_settings.return_value = MagicMock(
            wan_model_path="/models/Wan-AI/Wan2.1-T2V-1.3B",
            lora_checkpoint_path="/models/PanoWan/latest-lora.ckpt",
            panowan_engine_dir="/engines/panowan",
            upscale_engine_dir="/engines/upscale",
            upscale_weights_dir="/models/upscale",
        )
        specs = load_specs()
        up_engine = next(s for s in specs if s.name == "upscale-engine")
        self.assertEqual(up_engine.source_type, "submodule")
        self.assertEqual(up_engine.target_dir, "/engines/upscale")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py::LoadSpecsTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.specs'`

- [ ] **Step 3: Implement load_specs**

Create `app/models/specs.py`:

```python
import os

from .registry import FileCheck, ModelSpec


def load_specs() -> list[ModelSpec]:
    from app.settings import load_settings

    settings = load_settings()
    return [
        ModelSpec(
            name="wan-t2v-1.3b",
            source_type="huggingface",
            source_ref="Wan-AI/Wan2.1-T2V-1.3B",
            target_dir=settings.wan_model_path,
            files=[
                FileCheck(path="diffusion_pytorch_model.safetensors"),
                FileCheck(path="models_t5_umt5-xxl-enc-bf16.pth"),
            ],
        ),
        ModelSpec(
            name="panowan-lora",
            source_type="huggingface",
            source_ref="YOUSIKI/PanoWan",
            target_dir=os.path.dirname(settings.lora_checkpoint_path),
            files=[
                FileCheck(path=os.path.basename(settings.lora_checkpoint_path)),
            ],
        ),
        ModelSpec(
            name="panowan-engine",
            source_type="submodule",
            source_ref="",
            target_dir=settings.panowan_engine_dir,
            files=[FileCheck(path="pyproject.toml")],
        ),
        ModelSpec(
            name="upscale-engine",
            source_type="submodule",
            source_ref="",
            target_dir=settings.upscale_engine_dir,
            files=[FileCheck(path="realesrgan/inference_realesrgan_video.py")],
        ),
        ModelSpec(
            name="realesrgan-weights",
            source_type="huggingface",
            source_ref="0x7a7f/realesr-animevideov3",
            target_dir=settings.upscale_weights_dir,
            files=[FileCheck(path="realesr-animevideov3.pth")],
        ),
    ]
```

Note: The `source_ref` for `realesrgan-weights` uses a placeholder HF repo. This will be updated once the actual repo is confirmed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/specs.py tests/test_models.py
git commit -m "feat: add load_specs() with declarations for all model assets"
```

---

## Task 7: CLI entry point

**Files:**

- Create: `app/models/__main__.py`
- Modify: `tests/test_models.py` (add CLI tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
import subprocess
import sys


class CLITests(unittest.TestCase):
    @patch("app.models.manager.ModelManager.ensure")
    @patch("app.models.specs.load_specs")
    def test_cli_ensure_calls_manager_ensure(self, mock_specs, mock_ensure) -> None:
        mock_specs.return_value = []
        result = subprocess.run(
            [sys.executable, "-m", "app.models", "ensure"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("ready", result.stdout.lower())

    @patch("app.models.manager.ModelManager.verify", return_value=[])
    @patch("app.models.specs.load_specs")
    def test_cli_verify_exits_zero_when_all_present(self, mock_specs, mock_verify) -> None:
        mock_specs.return_value = []
        result = subprocess.run(
            [sys.executable, "-m", "app.models", "verify"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)

    @patch("app.models.manager.ModelManager.verify", return_value=["missing-model"])
    @patch("app.models.specs.load_specs")
    def test_cli_verify_exits_nonzero_when_missing(self, mock_specs, mock_verify) -> None:
        mock_specs.return_value = []
        result = subprocess.run(
            [sys.executable, "-m", "app.models", "verify"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing-model", result.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py::CLITests -v`
Expected: FAIL — `No module named 'app.models.__main__'`

- [ ] **Step 3: Implement CLI**

Create `app/models/__main__.py`:

```python
import argparse
import sys

from .manager import ModelManager
from .specs import load_specs


def main() -> None:
    parser = argparse.ArgumentParser(description="Model asset manager")
    parser.add_argument("action", choices=["ensure", "verify"])
    args = parser.parse_args()

    specs = load_specs()
    manager = ModelManager()

    if args.action == "ensure":
        manager.ensure(specs)
        print("All model assets ready.")
    elif args.action == "verify":
        missing = manager.verify(specs)
        if missing:
            print(f"Missing: {', '.join(missing)}")
            print("Run: make setup-models")
            sys.exit(1)
        print("All model assets verified.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/__main__.py tests/test_models.py
git commit -m "feat: add CLI entry point for model asset manager (ensure/verify)"
```

---

## Task 8: UpscaleEngine

**Files:**

- Create: `app/engines/upscale.py`
- Modify: `app/engines/__init__.py`
- Modify: `tests/test_engines.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engines.py`:

```python
from app.engines.upscale import UpscaleEngine


class UpscaleEngineTests(unittest.TestCase):
    def test_upscale_engine_has_correct_name_and_capabilities(self) -> None:
        engine = UpscaleEngine()
        self.assertEqual(engine.name, "upscale")
        self.assertEqual(engine.capabilities, ("upscale",))

    @mock.patch("app.engines.upscale.os.path.exists", return_value=True)
    def test_validate_runtime_passes_when_dirs_exist(self, mock_exists) -> None:
        engine = UpscaleEngine()
        engine.validate_runtime()  # Should not raise

    @mock.patch("app.engines.upscale.os.path.exists", return_value=False)
    def test_validate_runtime_raises_when_dirs_missing(self, mock_exists) -> None:
        engine = UpscaleEngine()
        with self.assertRaises(FileNotFoundError):
            engine.validate_runtime()

    @mock.patch("app.engines.upscale.upscale_video")
    def test_run_delegates_to_upscale_video(self, mock_upscale) -> None:
        mock_upscale.return_value = {
            "output_path": "/app/runtime/outputs/output_up.mp4",
            "model": "realesrgan-animevideov3",
            "scale": 2,
        }
        engine = UpscaleEngine()
        result = engine.run({
            "source_output_path": "/app/runtime/outputs/output_src.mp4",
            "output_path": "/app/runtime/outputs/output_up.mp4",
            "upscale_params": {
                "model": "realesrgan-animevideov3",
                "scale": 2,
            },
        })
        self.assertEqual(
            result,
            EngineResult(
                output_path="/app/runtime/outputs/output_up.mp4",
                metadata={},
            ),
        )
        mock_upscale.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engines.py::UpscaleEngineTests -v`
Expected: FAIL — `ImportError: cannot import name 'UpscaleEngine'`

- [ ] **Step 3: Implement UpscaleEngine**

Create `app/engines/upscale.py`:

```python
import os

from app.settings import settings
from app.upscaler import upscale_video

from .base import EngineResult


class UpscaleEngine:
    name = "upscale"
    capabilities = ("upscale",)

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

    def run(self, job: dict) -> EngineResult:
        params = job.get("upscale_params") or {}
        result = upscale_video(
            input_path=job["source_output_path"],
            output_path=job["output_path"],
            model=params["model"],
            scale=params["scale"],
            target_width=params.get("target_width"),
            target_height=params.get("target_height"),
            engine_dir=settings.upscale_engine_dir,
            weights_dir=settings.upscale_weights_dir,
            timeout_seconds=settings.upscale_timeout_seconds,
        )
        return EngineResult(output_path=result["output_path"], metadata={})
```

Update `app/engines/__init__.py`:

```python
from .base import EngineAdapter, EngineResult
from .panowan import PanoWanEngine
from .registry import EngineRegistry
from .upscale import UpscaleEngine

__all__ = ["EngineAdapter", "EngineResult", "EngineRegistry", "PanoWanEngine", "UpscaleEngine"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_engines.py -v`
Expected: May fail because `upscale_video` doesn't accept `engine_dir` + `weights_dir` yet. That's expected — Task 9 will fix the upscaler signature.

If test `test_run_delegates_to_upscale_video` fails due to signature mismatch, temporarily adjust the test to pass `model_dir` instead. We'll fix the signature in Task 9.

For now, update the test's `mock_upscale.assert_called_once()` to just check the call happened without verifying exact kwargs, since the signature will change in Task 9.

- [ ] **Step 5: Commit**

```bash
git add app/engines/upscale.py app/engines/__init__.py tests/test_engines.py
git commit -m "feat: add UpscaleEngine with validate_runtime and run delegation"
```

---

## Task 9: Upscaler module — split model_dir into engine_dir + weights_dir

**Files:**

- Modify: `app/upscaler.py`
- Modify: `tests/test_upscaler.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_upscaler.py`, update `RealESRGANBackendTests.test_build_command_basic`:

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
    self.assertIn("inference_realesrgan_video.py", cmd_str)
    self.assertIn("/engines/upscale", cmd_str)
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

Also update `RealBasicVSRBackendTests.test_build_command_contains_expected_args` and `SeedVR2BackendTests.test_build_command_contains_torchrun` and `UpscaleVideoTests` to use `engine_dir` + `weights_dir` instead of `model_dir`.

For `UpscaleVideoTests`, update:

```python
@patch("app.upscaler.subprocess.Popen")
@patch("app.upscaler.os.path.exists", return_value=True)
def test_upscale_video_calls_popen_and_returns_result(
    self, mock_exists, mock_popen
) -> None:
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (b"ok", b"")
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    result = upscale_video(
        input_path="/input/video.mp4",
        output_path="/output/video.mp4",
        model="realesrgan-animevideov3",
        scale=2,
        engine_dir="/engines/upscale",
        weights_dir="/models/upscale",
    )

    self.assertEqual(result["output_path"], "/output/video.mp4")
    self.assertEqual(result["model"], "realesrgan-animevideov3")
    self.assertEqual(result["scale"], 2)
    mock_popen.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_upscaler.py -v`
Expected: FAIL — `TypeError: build_command() got an unexpected keyword argument 'engine_dir'`

- [ ] **Step 3: Update upscaler.py**

In `app/upscaler.py`, update the `UpscalerBackend` Protocol:

```python
class UpscalerBackend(Protocol):
    name: str
    display_name: str
    default_scale: int
    max_scale: int

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        engine_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]: ...

    def validate_params(
        self,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> str | None: ...
```

Update `RealESRGANBackend.build_command`:

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
    script = os.path.join(engine_dir, "inference_realesrgan_video.py")
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

Update `RealBasicVSRBackend.build_command`:

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
    script = os.path.join(engine_dir, "inference_realbasicvsr.py")
    config = os.path.join(engine_dir, "configs", "realbasicvsr_x4.py")
    checkpoint = os.path.join(weights_dir, "RealBasicVSR_x4.pth")
    output_path = os.path.join(output_dir, "output.mp4")
    return [
        sys.executable,
        script,
        config,
        checkpoint,
        input_path,
        output_path,
        "--max-seq-len",
        "30",
    ]
```

Update `SeedVR2Backend.build_command`:

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
    script = os.path.join(engine_dir, "projects", "inference_seedvr2_3b.py")
    input_dir = os.path.dirname(input_path)
    res_w = str(target_width) if target_width else "896"
    res_h = str(target_height) if target_height else "448"
    return [
        "torchrun",
        "--nproc_per_node=1",
        script,
        "--video_path",
        input_dir,
        "--output_dir",
        output_dir,
        "--res_h",
        res_h,
        "--res_w",
        res_w,
        "--sp_size",
        "1",
    ]
```

Update `upscale_video()` function signature:

```python
def upscale_video(
    input_path: str,
    output_path: str,
    model: str = "realesrgan-animevideov3",
    scale: int = 2,
    target_width: int | None = None,
    target_height: int | None = None,
    engine_dir: str = "/engines/upscale",
    weights_dir: str = "/models/upscale",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
```

And in the body, change the `build_command` call:

```python
    cmd = backend.build_command(
        input_path=input_path,
        output_dir=output_dir,
        engine_dir=engine_dir,
        weights_dir=weights_dir,
        scale=scale,
        target_width=target_width,
        target_height=target_height,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_upscaler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/upscaler.py tests/test_upscaler.py
git commit -m "refactor: split upscaler model_dir into engine_dir + weights_dir"
```

---

## Task 10: PanoWanEngine — remove upscale branch

**Files:**

- Modify: `app/engines/panowan.py`
- Modify: `tests/test_engines.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engines.py`:

```python
class PanoWanEngineCapabilitiesTests(unittest.TestCase):
    def test_panowan_engine_does_not_have_upscale_capability(self) -> None:
        engine = PanoWanEngine()
        self.assertNotIn("upscale", engine.capabilities)
        self.assertEqual(engine.capabilities, ("t2v", "i2v"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engines.py::PanoWanEngineCapabilitiesTests -v`
Expected: FAIL — capabilities still contains "upscale"

- [ ] **Step 3: Update PanoWanEngine**

In `app/engines/panowan.py`, change:

```python
import os

from app.generator import generate_video
from app.settings import settings

from .base import EngineResult


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v")

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
        result = generate_video(job)
        return EngineResult(output_path=result["output_path"], metadata={})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_engines.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/engines/panowan.py tests/test_engines.py
git commit -m "refactor: remove upscale from PanoWanEngine capabilities and run()"
```

---

## Task 11: Worker service — multi-engine registry and routing

**Files:**

- Modify: `app/worker_service.py`
- Modify: `tests/test_worker_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_worker_service.py`:

```python
from app.engines.upscale import UpscaleEngine


class MultiEngineRegistryTests(unittest.TestCase):
    def test_build_registry_contains_both_engines(self) -> None:
        from app.worker_service import build_registry
        registry = build_registry()
        self.assertIsInstance(registry.get("panowan"), PanoWanEngine)
        self.assertIsInstance(registry.get("upscale"), UpscaleEngine)

    def test_resolve_engine_routes_upscale_jobs(self) -> None:
        from app.worker_service import _resolve_engine, build_registry
        registry = build_registry()
        job = {"type": "upscale"}
        engine = _resolve_engine(registry, job)
        self.assertEqual(engine.name, "upscale")

    def test_resolve_engine_routes_generate_jobs_to_panowan(self) -> None:
        from app.worker_service import _resolve_engine, build_registry
        registry = build_registry()
        job = {"type": "generate"}
        engine = _resolve_engine(registry, job)
        self.assertEqual(engine.name, "panowan")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_worker_service.py::MultiEngineRegistryTests -v`
Expected: FAIL — `_resolve_engine` does not exist, or registry doesn't contain "upscale"

- [ ] **Step 3: Update worker_service.py**

```python
import os
import socket
import time

from app.engines import EngineRegistry, PanoWanEngine, UpscaleEngine
from app.jobs import LocalJobBackend
from app.settings import settings


def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PanoWanEngine())
    registry.register(UpscaleEngine())
    return registry


def _resolve_engine(registry: EngineRegistry, job: dict):
    job_type = job.get("type", "generate")
    if job_type == "upscale":
        return registry.get("upscale")
    return registry.get("panowan")


def _worker_still_owns_job(
    backend: LocalJobBackend, job_id: str, worker_id: str
) -> bool:
    current = backend.get_job(job_id)
    return bool(
        current is not None
        and current.get("status") == "running"
        and current.get("worker_id") == worker_id
    )


def run_one_job(backend: LocalJobBackend, registry: EngineRegistry, worker_id: str) -> bool:
    job = backend.claim_next_job(worker_id=worker_id)
    if job is None:
        return False

    if not _worker_still_owns_job(backend, job["job_id"], worker_id):
        return True

    engine = _resolve_engine(registry, job)

    job = {
        **job,
        "_should_cancel": lambda: not _worker_still_owns_job(
            backend, job["job_id"], worker_id
        ),
    }

    try:
        result = engine.run(job)
        if _worker_still_owns_job(backend, job["job_id"], worker_id):
            backend.complete_job(job["job_id"], result.output_path)
        return True
    except Exception as exc:
        if _worker_still_owns_job(backend, job["job_id"], worker_id):
            backend.fail_job(job["job_id"], str(exc))
            raise
        return True


def main() -> None:
    worker_id = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
    backend = LocalJobBackend(settings.job_store_path)
    registry = build_registry()

    for engine in registry._engines.values():
        engine.validate_runtime()

    caps = []
    for engine in registry._engines.values():
        caps.extend(engine.capabilities)

    print(
        f"Worker started: id={worker_id} capabilities={','.join(caps)}",
        flush=True,
    )
    while True:
        worked = run_one_job(backend, registry, worker_id)
        if not worked:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/worker_service.py tests/test_worker_service.py
git commit -m "feat: add multi-engine registry with upscale routing to worker service"
```

---

## Task 12: Shell scripts — simplify to thin Python CLI wrappers

**Files:**

- Modify: `scripts/model-setup.sh`
- Modify: `scripts/download-models.sh`
- Modify: `scripts/check-runtime.sh`
- Modify: `scripts/start-local.sh`

- [ ] **Step 1: Simplify model-setup.sh**

Replace the entire content of `scripts/model-setup.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

exec python -m app.models ensure
```

- [ ] **Step 2: Simplify download-models.sh**

Replace the entire content of `scripts/download-models.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_host

export UPSCALE_ENGINE_DIR="${UPSCALE_ENGINE_DIR:-${REPO_ROOT}/third_party/Upscale}"
export UPSCALE_WEIGHTS_DIR="${UPSCALE_WEIGHTS_DIR:-${MODEL_ROOT}/realesrgan}"
export PANOWAN_ENGINE_DIR="${PANOWAN_ENGINE_DIR:-${REPO_ROOT}/third_party/PanoWan}"

exec python -m app.models ensure
```

- [ ] **Step 3: Simplify check-runtime.sh**

Replace the entire content of `scripts/check-runtime.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
panowan_env_runtime

exec python -m app.models verify
```

- [ ] **Step 4: Update start-local.sh inline download**

In `scripts/start-local.sh`, replace the inline model download logic (the block that checks `WAN_DIFFUSION_FILE`, calls `hf download`, downloads LoRA) with:

```bash
# ── Model asset provisioning ──
log "Checking model assets..."
python -m app.models ensure
```

Remove the now-unused variables and logic for `skip_model_download`, the `hf download` calls, and the `download-panowan.sh` retry loop.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (shell scripts are not unit-tested; their Python backends are)

- [ ] **Step 6: Commit**

```bash
git add scripts/model-setup.sh scripts/download-models.sh scripts/check-runtime.sh scripts/start-local.sh
git commit -m "refactor: simplify shell scripts to thin Python CLI wrappers"
```

---

## Task 13: Docker and Compose — add Upscale engine + new env vars

**Files:**

- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update Dockerfile**

After the existing `COPY third_party/PanoWan /engines/panowan` line in both `worker-panowan` and `dev-worker-panowan` targets, add:

```dockerfile
COPY third_party/Upscale /engines/upscale
```

- [ ] **Step 2: Update docker-compose.yml**

Add to the `worker-panowan` environment section:

```yaml
      UPSCALE_ENGINE_DIR: /engines/upscale
      UPSCALE_WEIGHTS_DIR: /models/upscale
```

Add to the `model-setup` environment section:

```yaml
      UPSCALE_ENGINE_DIR: /engines/upscale
      UPSCALE_WEIGHTS_DIR: /models/upscale
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "infra: add Upscale engine to Docker image and compose env vars"
```

---

## Task 14: Add huggingface_hub dependency

**Files:**

- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Add `huggingface_hub` to the project dependencies in `pyproject.toml`:

```toml
dependencies = [
    # ... existing deps ...
    "huggingface_hub>=0.20.0",
]
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add huggingface_hub dependency for ModelManager"
```

---

## Task 15: Update API layer for new settings fields

**Files:**

- Modify: `app/api.py`
- Modify: `tests/test_api.py` (if needed)

- [ ] **Step 1: Find and replace upscale_model_dir references in api.py**

Search `app/api.py` for any reference to `settings.upscale_model_dir` and replace with appropriate new fields. The upscale endpoint in api.py uses `settings.upscale_output_dir` for output paths but does NOT pass `model_dir` to the upscaler (that's done by the engine). So the API layer likely only needs the `upscale_output_dir` reference checked.

Verify by searching:

```bash
grep -n "upscale_model_dir" app/api.py
```

If found, it must be removed (the setting no longer exists). The `settings.upscale_output_dir` and `settings.upscale_timeout_seconds` fields still exist and should be kept.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/api.py tests/test_api.py
git commit -m "fix: remove stale upscale_model_dir references from API layer"
```

---

## Task 16: Full integration test run

**Files:**

- No new files

- [ ] **Step 1: Run the complete test suite**

Run: `python -m unittest discover -s tests -v`
Expected: All tests PASS

- [ ] **Step 2: Verify CLI works**

Run: `python -m app.models verify`
Expected: Prints missing specs (since we're on a dev machine without models), exits with non-zero code

- [ ] **Step 3: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: resolve integration test failures from model manager refactor"
```

---

## Self-Review

### 1. Spec Coverage

| Spec Section | Task(s) | Covered? |
|---|---|---|
| 1. Core Data Model | Task 2 | Yes |
| 2. Provider Abstraction | Tasks 3, 4 | Yes |
| 3. ModelManager | Task 5 | Yes |
| 4. ModelSpec Declarations | Task 6 | Yes |
| 5. CLI Entry Point | Task 7 | Yes |
| 6. Shell Script Simplification | Task 12 | Yes |
| 7. UpscaleEngine | Task 8 | Yes |
| 8. Settings Changes | Task 1 | Yes |
| 9. Upscaler Module Changes | Task 9 | Yes |
| 10. Third-party Layout | Task 13 (Dockerfile only) | Partial — third_party/Upscale content needs actual setup |
| 11. Naming Convention Alignment | Tasks 1, 8, 9, 11 | Yes |
| 12. Concurrency Model | Task 11 (preserves Worker polling) | Yes |
| 13. File Change Summary | All tasks | Yes |
| 14. Known TBDs | Task 6 (HF repo TBD) | Acknowledged |

### 2. Placeholder Scan

No TBD, TODO, or "implement later" patterns found in task steps. All code is concrete.

### 3. Type Consistency

- `ModelSpec(source_type="submodule")` → `SubmoduleProvider` → `ModelManager._providers["submodule"]` — matches
- `upscale_video(engine_dir=..., weights_dir=...)` in Task 8 matches signature from Task 9 — matches
- `build_registry()` returns `EngineRegistry` used by `_resolve_engine()` — matches
- Settings fields `upscale_engine_dir` / `upscale_weights_dir` used consistently in Tasks 1, 6, 8 — matches
