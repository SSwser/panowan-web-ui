# Upscale Backend Integration Design

## Overview

`UpscaleEngine` is the product-level engine for all video upscaling. Individual model families such as RealESRGAN, RealBasicVSR, and SeedVR2 are backend implementations under that engine, not separate top-level engines.

This spec defines the target design for integrating multiple upscale backends without preserving temporary bridge behavior or exposing models that cannot run. It complements `2026-04-25-model-download-manager-design.md`; it does not replace the general Model Download Manager.

## Goals

- Keep one stable product-level engine path: `third_party/Upscale` in the repository and `/engines/upscale` in the container.
- Keep one stable weights root: `/models/upscale`.
- Store each backend under a deterministic backend subdirectory.
- Separate registered backend metadata from runtime-available backend choices.
- Prevent API/UI from offering an upscale model unless its scripts, weights, and runtime dependencies are available.
- Make RealESRGAN the first fully supported backend, while allowing RealBasicVSR and SeedVR2 to be integrated later without changing the public engine contract.

## Non-goals

- Do not support legacy top-level `third_party/RealESRGAN`, `/engines/realesrgan`, or `REALESRGAN_*` runtime names.
- Do not keep compatibility shims for `upscale_model_dir`.
- Do not force RealBasicVSR and SeedVR2 into the default runtime image before their dependency and GPU requirements are fully validated.
- Do not treat a bridge launcher as sufficient runtime readiness.

## Directory Contract

Repository layout:

```text
third_party/
├── PanoWan/
└── Upscale/
    ├── README.md
    ├── realesrgan/
    │   ├── adapter.py
    │   └── vendor/
    ├── realbasicvsr/
    │   ├── adapter.py
    │   ├── configs/
    │   └── vendor/
    └── seedvr2/
        ├── adapter.py
        └── vendor/
```

Container layout:

```text
/engines/
├── panowan/
└── upscale/
    ├── realesrgan/
    ├── realbasicvsr/
    └── seedvr2/

/models/
└── upscale/
    ├── realesrgan/
    ├── realbasicvsr/
    └── seedvr2/
```

The top-level `third_party/Upscale` directory is repository-managed. Individual backend directories may contain vendored source snapshots, thin adapters, or future submodules, but callers must only depend on the stable `/engines/upscale/<backend>` contract.

## Backend Metadata Model

Each backend exposes metadata describing how to validate and execute it.

```python
@dataclass(frozen=True)
class UpscaleBackendAssets:
    engine_files: tuple[str, ...]
    weight_files: tuple[str, ...]
    required_commands: tuple[str, ...] = ()
    runtime_python: str | None = None
    required_python_modules: tuple[str, ...] = ()

class UpscalerBackend(Protocol):
    name: str
    display_name: str
    default_scale: int
    max_scale: int
    assets: UpscaleBackendAssets

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

`engine_files` are relative to `/engines/upscale`. `weight_files` are relative to `/models/upscale`. This keeps backend checks independent of host/container path differences.

## Registry Semantics

There are two backend sets:

1. **Registered backends** — all backend implementations known to the codebase.
2. **Available backends** — registered backends whose runtime assets and required commands pass validation in the current environment.

`UPSCALE_BACKENDS` remains the registered catalog. API and UI must use available backends, not the raw catalog, when accepting or presenting model choices.

Suggested helper API:

```python
def get_available_upscale_backends(
    engine_dir: str,
    weights_dir: str,
    backends: Mapping[str, UpscalerBackend] = UPSCALE_BACKENDS,
) -> dict[str, UpscalerBackend]:
    ...
```

A backend is available only when:

- every required engine file exists under `engine_dir`,
- every required weight file exists under `weights_dir`,
- every required command is discoverable with `shutil.which`,
- and any backend-specific runtime probe passes.

## Backend Contracts

### RealESRGAN

Backend name: `realesrgan-animevideov3`

Required engine files:

```text
realesrgan/adapter.py
realesrgan/vendor/Real-ESRGAN/inference_realesrgan_video.py
realesrgan/vendor/Real-ESRGAN/realesrgan/__init__.py
realesrgan/vendor/Real-ESRGAN/realesrgan/utils.py
realesrgan/vendor/Real-ESRGAN/realesrgan/archs/__init__.py
realesrgan/vendor/Real-ESRGAN/realesrgan/archs/srvgg_arch.py
```

Required weight files:

```text
realesrgan/realesr-animevideov3.pth
```

RealESRGAN is the first backend to make fully available. The deterministic adapter executes a trimmed vendored runtime bundle from the backend directory. The vendored package keeps only the anime-video inference path and slim `__init__.py` files so importing `realesrgan` does not pull training/data/version modules.

Command shape:

```text
/opt/venvs/upscale-realesrgan/bin/python /engines/upscale/realesrgan/adapter.py \
  -i <input_path> \
  -o <output_dir> \
  -n realesr-animevideov3 \
    --model_path /models/upscale/realesrgan/realesr-animevideov3.pth \
    -s <scale>
```

Runtime availability probe:

- runtime python: `/opt/venvs/upscale-realesrgan/bin/python`
- required modules: `cv2`, `ffmpeg`, `tqdm`
- required command: `ffmpeg`

### RealBasicVSR

Backend name: `realbasicvsr`

Required engine files:

```text
realbasicvsr/adapter.py
realbasicvsr/configs/realbasicvsr_x4.py
```

Required weight files:

```text
realbasicvsr/RealBasicVSR_x4.pth
```

RealBasicVSR is not available until its OpenMMLab dependency stack is validated in the worker image. It may remain registered but unavailable.

Command shape:

```text
python /engines/upscale/realbasicvsr/adapter.py \
  /engines/upscale/realbasicvsr/configs/realbasicvsr_x4.py \
  /models/upscale/realbasicvsr/RealBasicVSR_x4.pth \
  <input_path> \
  <output_path> \
  --max-seq-len 30
```

### SeedVR2

Backend name: `seedvr2-3b`

Required engine files:

```text
seedvr2/projects/inference_seedvr2_3b.py
```

Required weight files:

```text
seedvr2/seedvr2_ema_3b.pth
seedvr2/ema_vae.pth
seedvr2/pos_emb.pt
seedvr2/neg_emb.pt
```

Required commands:

```text
torchrun
```

SeedVR2 is a heavyweight backend and should be treated as an optional runtime profile. It is registered in code only after the command and asset contract is represented, but it must not be available in the default worker until its CUDA, PyTorch, flash attention, and VRAM constraints are validated.

Command shape:

```text
torchrun --nproc_per_node=1 /engines/upscale/seedvr2/projects/inference_seedvr2_3b.py \
  --video_path <input_dir> \
  --output_dir <output_dir> \
  --res_h <target_height> \
  --res_w <target_width> \
  --sp_size 1
```

## ModelSpec Integration

Model specs should mirror the backend contract.

Initial required specs:

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
)

ModelSpec(
    name="upscale-realesrgan-weights",
    source_type="http",
    source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
    target_dir=container_child(settings.upscale_weights_dir, "realesrgan"),
    files=[FileCheck(path="realesr-animevideov3.pth", sha256="<verified-sha256>")],
)
```

RealESRGAN weights are distributed as an official release artifact, not as a stable HuggingFace snapshot in this project. Implementation must compute and pin the checked digest from that artifact before treating the backend as production-ready.

RealBasicVSR and SeedVR2 specs should be added only when their runtime profiles are ready to be supported. Adding a spec means the manager is expected to provision or verify that backend for the selected profile.

## API Behavior

`POST /upscale` must reject any model that is registered but not available in the current runtime.

Error shape:

```text
Model '<name>' is not available in this worker runtime. Available models: <list>
```

The default model remains `realesrgan-animevideov3`, but default selection must also pass availability validation. If no upscale backend is available, `/upscale` should fail before creating a job.

A future model-list endpoint can expose both registered and available metadata, but job creation should only accept available models.

## Worker Runtime Validation

`UpscaleEngine.validate_runtime()` should not only check that `settings.upscale_engine_dir` and `settings.upscale_weights_dir` exist. It should validate that at least one backend is available.

Startup should fail when no upscale backend is available, because the worker advertises `upscale` capability only if it can run at least one upscale model.

For future multi-worker profiles, a worker may advertise more specific metadata such as:

```text
capabilities=upscale
upscale_models=realesrgan-animevideov3,seedvr2-3b
```

## Error Handling

- Missing backend engine files produce a setup-oriented error pointing to `/engines/upscale/<backend>`.
- Missing weights produce a setup-oriented error pointing to `/models/upscale/<backend>` and `make setup-models`.
- Missing commands produce a dependency-oriented error naming the command and backend.
- Parameter validation remains backend-specific and happens before job creation.
- Subprocess failure remains a runtime error with stderr tail preserved.

## Testing Strategy

Update tests around three distinct concepts:

1. **Registered catalog tests**
   - all intended backend classes can be instantiated,
   - each backend declares assets,
   - command construction uses `/engines/upscale/<backend>` and `/models/upscale/<backend>`.

2. **Availability tests**
   - backend is unavailable when an engine file is missing,
   - backend is unavailable when a weight file is missing,
   - backend is unavailable when a required command is missing,
   - backend is available when all declared assets exist.

3. **API / worker tests**
   - `/upscale` rejects registered-but-unavailable models,
   - `/upscale` creates a job for an available model,
   - `UpscaleEngine.validate_runtime()` fails when zero backends are available,
   - worker only advertises upscale capability when validation passes.

Existing tests that assert all three backend names are directly usable should be rewritten to distinguish registered from available.

## Migration From Current Code

This is a breaking internal cleanup.

- Replace the current RealESRGAN bridge launcher with `realesrgan/adapter.py` plus deterministic vendored runner path.
- Remove environment-variable runner discovery from the target RealESRGAN execution path.
- Change `RealESRGANBackend.build_command()` to call `realesrgan/adapter.py`.
- Add backend asset declarations to each backend class.
- Add availability filtering and use it in API validation.
- Change `UpscaleEngine.validate_runtime()` to require at least one available backend.
- Update `app/models/specs.py` to verify RealESRGAN adapter and vendored runner, not just the old bridge file.
- Fix stale plan text that still points `UPSCALE_WEIGHTS_DIR` to `${MODEL_ROOT}/realesrgan`.
- Update the model-download-manager spec line about RealBasicVSR and SeedVR2 so they use backend subdirectories under `upscale_engine_dir` and `upscale_weights_dir`, not separate top-level engine dirs.

## Recommended Implementation Order

1. Introduce backend asset metadata and availability filtering.
2. Update API and worker validation to use available backends.
3. Convert RealESRGAN from bridge launcher to deterministic adapter + vendored runner contract.
4. Update ModelSpec declarations for RealESRGAN engine and weights.
5. Rewrite tests to separate registered catalog from available runtime.
6. Keep RealBasicVSR and SeedVR2 registered only if they have complete asset metadata; otherwise remove them from user-facing availability until their profiles are implemented.

## Open Verification Items

These are not design choices; they must be verified during implementation:

- the authoritative RealESRGAN weight source and expected checksum,
- the exact upstream RealESRGAN video runner file set needed by the adapter,
- the RealBasicVSR dependency versions compatible with the worker image,
- SeedVR2 runtime requirements for the target GPU environment.
