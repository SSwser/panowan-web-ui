# Model Download Manager Design

> Final implementation update (2026-04-25): the engine layer now uses generic Upscale naming.
>
> - `third_party/Upscale`
> - `/engines/upscale`
> - `UPSCALE_ENGINE_DIR`, `UPSCALE_WEIGHTS_DIR`
> - `upscale_engine_dir`, `upscale_weights_dir`
>
> `RealESRGAN` remains a backend under `third_party/Upscale/realesrgan/`. Any older `third_party/RealESRGAN` or `realesrgan_*` top-level engine names below are superseded draft names.

## Overview

Unify model asset provisioning into a single Python-based system with a declarative registry, replacing the duplicated model-setup logic currently spread across `download-models.sh`, `model-setup.sh`, and `start-local.sh`. Introduce an `UpscaleEngine` peer to `PanoWanEngine`, and restructure the third_party layout so that Upscale has its own engine bundle and Real-ESRGAN lives under it as a backend implementation.

This is a breaking change for internal settings and runtime path layout. The legacy shell entrypoints are retained only as thin wrappers around the new Python CLI so existing operator workflows (`make setup-models`, host convenience scripts) do not need to change immediately.

## 1. Core Data Model

### ModelSpec

```python
@dataclass(frozen=True)
class ModelSpec:
    name: str                    # Unique identifier: "wan-t2v-1.3b", "realesrgan-weights"
    source_type: str             # "huggingface" | "submodule"
    source_ref: str              # HF repo_id / empty (submodule)
    target_dir: str              # Download/verification target directory
    files: list[FileCheck]       # Files to verify

@dataclass(frozen=True)
class FileCheck:
    path: str                    # Relative to target_dir
    sha256: str | None = None    # Optional hash; None = existence check only
```

### source_type semantics

| source_type | Meaning | Action |
|---|---|---|
| `huggingface` | Download from Hugging Face Hub | `snapshot_download()` then verify |
| `submodule` | Built into Docker image via `third_party/` | Verify existence only, no download |

## 2. Provider Abstraction

```python
class ModelProvider(Protocol):
    def ensure(self, spec: ModelSpec) -> None: ...
    def verify(self, spec: ModelSpec) -> None: ...
```

### HuggingFaceProvider

1. `verify(spec)` checks whether all `spec.files` exist and hashes match; if not, raise `FileNotFoundError` or `RuntimeError`
2. `ensure(spec)` calls `verify(spec)` first
3. If verification fails → `huggingface_hub.snapshot_download(repo_id=spec.source_ref, local_dir=spec.target_dir)`
4. Post-download verification: all files must exist and match hashes

### SubmoduleProvider

1. `verify(spec)` checks `os.path.exists(os.path.join(spec.target_dir, f.path))` for each file
2. If missing → raise `FileNotFoundError` with instruction: "This should be included in the Docker image via third_party/"
3. `ensure(spec)` delegates to `verify(spec)` because no download step exists for submodule-backed assets

## 3. ModelManager

```python
class ModelManager:
    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {
            "huggingface": HuggingFaceProvider(),
            "submodule": SubmoduleProvider(),
        }

    def ensure(self, specs: list[ModelSpec]) -> None:
        """Download missing assets, verify all. Raises on failure."""
        for spec in specs:
            self._providers[spec.source_type].ensure(spec)

    def verify(self, specs: list[ModelSpec]) -> list[str]:
        """Read-only check. Returns list of missing spec names."""
        missing = []
        for spec in specs:
            try:
                self._providers[spec.source_type].verify(spec)
            except (FileNotFoundError, RuntimeError):
                missing.append(spec.name)
        return missing
```

- `ensure` — destructive (triggers download), used by `make setup-models`
- `verify` — read-only (no download), used by worker startup and health checks

## 4. ModelSpec Declarations

```python
def load_specs(settings: Settings) -> list[ModelSpec]:
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
            name="upscale-realesrgan-engine",
            source_type="submodule",
            source_ref="",
            target_dir=settings.upscale_engine_dir,
            files=[
                FileCheck(path="realesrgan/adapter.py"),
                FileCheck(path="realesrgan/vendor/inference_realesrgan_video.py"),
            ],
        ),
        ModelSpec(
            name="upscale-realesrgan-weights",
            source_type="http",
            source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
            target_dir=container_child(settings.upscale_weights_dir, "realesrgan"),
            files=[
                FileCheck(
                    path="realesr-animevideov3.pth",
                    sha256="b8a8376811077954d82ca3fcf476f1ac3da3e8a68a4f4d71363008000a18b75d",
                ),
            ],
        ),
    ]
```

Key principle: `target_dir` values come from `settings`, so the same declaration works in both container (`/models/...`) and host (`./data/models/...`) contexts via different environment variables.

## 5. CLI Entry Point

```python
# app/models/__main__.py
"""python -m app.models [ensure|verify]"""

def main():
    parser = argparse.ArgumentParser(description="Model asset manager")
    parser.add_argument("action", choices=["ensure", "verify"])
    args = parser.parse_args()

    settings = load_settings()
    specs = load_specs(settings)
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
```

## 6. Shell Script Simplification

### Simplified (not deleted)

| Script | New content |
|---|---|
| `scripts/model-setup.sh` | `exec python -m app.models ensure` |
| `scripts/download-models.sh` | Set host env vars + `python -m app.models ensure` |
| `scripts/check-runtime.sh` | `exec python -m app.models verify` |
| `scripts/start-local.sh` inline download | Replace with `python -m app.models ensure` |

## 7. UpscaleEngine

### New file: `app/engines/upscale.py`

```python
class UpscaleEngine:
    name = "upscale"
    capabilities = ("upscale",)

    def validate_runtime(self) -> None:
        missing = []
        for path in (settings.upscale_engine_dir, settings.upscale_weights_dir):
            if not os.path.exists(path):
                missing.append(path)
        if missing:
            raise FileNotFoundError(...)

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

### PanoWanEngine changes

- Remove `upscale` from `capabilities`: `("t2v", "i2v")` only
- Remove `if job_type == "upscale"` branch from `run()`
- Remove `from app.upscaler import upscale_video` import

### Worker service changes

```python
def build_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(PanoWanEngine())
    registry.register(UpscaleEngine())
    return registry

def _resolve_engine(registry: EngineRegistry, job: dict) -> EngineAdapter:
    job_type = job.get("type", "generate")
    if job_type == "upscale":
        return registry.get("upscale")
    return registry.get("panowan")
```

Single worker process, multiple engines, job type routing.

## 8. Settings Changes

### Removed

```python
upscale_model_dir: str
```

### Added

```python
upscale_engine_dir: str   # /engines/upscale (scripts, image-builtin)
upscale_weights_dir: str  # /models/upscale (weights, HF download)
```

### Environment variables

```bash
UPSCALE_ENGINE_DIR=/engines/upscale
UPSCALE_WEIGHTS_DIR=/models/upscale
```

## 9. Upscaler Module Changes

### `upscale_video()` signature change

```python
# Before
def upscale_video(
    input_path: str, output_path: str, model: str = "realesrgan-animevideov3",
    scale: int = 2, target_width: int | None = None, target_height: int | None = None,
    model_dir: str = "/app/data/models/upscale", timeout_seconds: int = 1800,
) -> dict[str, Any]

# After
def upscale_video(
    input_path: str, output_path: str, model: str = "realesrgan-animevideov3",
    scale: int = 2, target_width: int | None = None, target_height: int | None = None,
    engine_dir: str = "/engines/upscale", weights_dir: str = "/models/upscale",
    timeout_seconds: int = 1800,
) -> dict[str, Any]
```

The `model_dir` parameter is replaced by `engine_dir` (for script paths) and `weights_dir` (for weight file paths). Inside `upscale_video()`, `backend.build_command()` receives both and uses them appropriately.

### `UpscalerBackend.build_command()` signature change

```python
# Before
def build_command(self, ..., model_dir: str) -> list[str]

# After
def build_command(self, ..., engine_dir: str, weights_dir: str) -> list[str]
```

Each backend implementation uses `engine_dir` to locate inference scripts and `weights_dir` to locate model weight files.

### Scripts vs weights separation

- `/engines/upscale/` — project-owned engine bundle (image-builtin, `SubmoduleProvider`)
- `/models/upscale/realesrgan/` — RealESRGAN weights (HF download, `HuggingFaceProvider`)

`RealESRGANBackend.build_command()` uses `engine_dir` for script path and `weights_dir` for model weight path.

## 10. Third-party Layout

| Directory | Content | Git management |
|---|---|---|
| `third_party/PanoWan/` | PanoWan engine source | git submodule |
| `third_party/Upscale/` | Upscale engine bundle and backend launchers | repository-managed |

### Dockerfile

```dockerfile
# Existing
COPY third_party/PanoWan /engines/panowan

# New
COPY third_party/Upscale /engines/upscale
```

The RealESRGAN backend remains nested under `third_party/Upscale/realesrgan/`,
but the top-level bundle is owned by this repository so UpscaleEngine can host
multiple backends under one stable runtime path.

## 11. Naming Convention Alignment

All third-party engine components follow the same pattern:

| Layer | PanoWan | Upscale |
|---|---|---|
| `third_party/` directory | `third_party/PanoWan` | `third_party/Upscale` |
| Container path | `/engines/panowan` | `/engines/upscale` |
| Environment variable | `PANOWAN_ENGINE_DIR` | `UPSCALE_ENGINE_DIR` |
| Python class | `PanoWanEngine` | `UpscaleEngine` |
| Engine registry name | `"panowan"` | `"upscale"` |
| Capabilities | `t2v, i2v` | `upscale` |

## 12. Concurrency Model

Confirmed: **Worker polling model** (current implementation).

- API layer creates job records only, does not manage GPU or subprocess
- Worker process polls `claim_next_job()`, runs `engine.run(job)`, reports result
- Single worker = serial GPU execution by design, no `Semaphore` needed
- Cancel: API updates job status, Worker checks `_should_cancel()` on next poll

This differs from the original video-upscale spec which used `threading.Semaphore(1)` + API `background_tasks`. The worker polling model is the authoritative design.

## 13. File Change Summary

| File | Change |
|---|---|
| `app/models/__init__.py` | **New** — module init |
| `app/models/registry.py` | **New** — ModelSpec, FileCheck |
| `app/models/providers.py` | **New** — HuggingFaceProvider, SubmoduleProvider |
| `app/models/manager.py` | **New** — ModelManager |
| `app/models/specs.py` | **New** — load_specs() |
| `app/models/__main__.py` | **New** — CLI: ensure/verify |
| `app/engines/upscale.py` | **New** — UpscaleEngine |
| `app/engines/panowan.py` | Remove upscale branch, capabilities → t2v+i2v |
| `app/engines/__init__.py` | Export UpscaleEngine |
| `app/upscaler.py` | `model_dir` → `engine_dir` + `weights_dir` |
| `app/settings.py` | Remove `upscale_model_dir`, add `upscale_engine_dir` + `upscale_weights_dir` |
| `app/worker_service.py` | Register UpscaleEngine, add `_resolve_engine()` |
| `scripts/model-setup.sh` | Simplify to `python -m app.models ensure` |
| `scripts/download-models.sh` | Simplify to env vars + `python -m app.models ensure` |
| `scripts/check-runtime.sh` | Simplify to `python -m app.models verify` |
| `scripts/start-local.sh` | Replace inline download with `python -m app.models ensure` |
| `Dockerfile` | Add `COPY third_party/Upscale /engines/upscale` |
| `docker-compose.yml` | Add `UPSCALE_ENGINE_DIR`, `UPSCALE_WEIGHTS_DIR` |
| `.env.example` | Update upscale section with new env vars |
| `third_party/Upscale/` | **New** — repository-managed engine bundle |
| `tests/test_models.py` | **New** — ModelManager, providers, specs tests |
| `tests/test_upscaler.py` | Update for `engine_dir`+`weights_dir` |
| `tests/test_settings.py` | Update for new settings fields |
| `tests/test_engines.py` | Add UpscaleEngine tests |
| `tests/test_worker_service.py` | Update for multi-engine registry |

## 14. Known TBDs

- `realesrgan-weights` spec: HF `source_ref` repo needs to be identified
- RealBasicVSR and SeedVR2 backends: follow same `third_party/` pattern when ready, with their own engine_dirs and weights_dirs
- `pyproject.toml`: `huggingface_hub` dependency needed for `HuggingFaceProvider`
