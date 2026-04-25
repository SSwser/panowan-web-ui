# ADR 0002: Unified Model Download Manager

Date: 2026-04-25
Status: Superseded by ADR 0005: Backend Acquisition and Setup

## Context

> Superseded by ADR 0005: Backend Acquisition and Setup.
> Keep this record for historical context; do not treat the setup-model framing as current architecture.


Model download logic is duplicated across three shell entrypoints: `download-models.sh` (host), `model-setup.sh` (container), and `start-local.sh` (inline). They each contain overlapping Wan/LoRA provisioning behavior with different environment variable contexts. None of them cover upscale model provisioning, which is why the upscale feature fails at runtime with missing files.

Adding upscale model downloads as a fourth patch to each script would deepen the duplication problem. Adding a fifth model type later would require editing all three scripts again.

## Decision

Replace all shell-based download logic with a unified Python model download manager:

1. **Declarative ModelSpec registry** — each model artifact is a dataclass declaring its source type (`huggingface` | `submodule`), target directory, and files to verify
2. **Provider abstraction** — `HuggingFaceProvider` for HF Hub downloads, `SubmoduleProvider` for image-builtin verification
3. **ModelManager** — single entry point with `ensure()` (download + verify) and `verify()` (read-only check)
4. **CLI** — `python -m app.models [ensure|verify]`
5. **Shell scripts** — retained only as thin wrappers that call the Python CLI

This record is historical. The current architecture supersedes the module-only setup framing with a broader backend acquisition and setup boundary.

Additionally, introduce an **UpscaleEngine** peer to PanoWanEngine, moving upscale capability out of PanoWanEngine. This aligns with ADR 0001's engine-oriented architecture and enables independent deployment and validation of upscale assets.

The final engine-layer naming is generic:

- `third_party/PanoWan` remains the PanoWan engine bundle.
- `third_party/Upscale` is the project-owned Upscale engine bundle.
- `RealESRGAN` is treated as a backend implementation under `third_party/Upscale/realesrgan/`, not as the top-level engine directory.
- Runtime settings use `upscale_engine_dir` and `upscale_weights_dir` (`UPSCALE_ENGINE_DIR`, `UPSCALE_WEIGHTS_DIR`).

## Consequences

### Positive

- Adding a new model = adding one `ModelSpec` declaration. No script editing required.
- Single source of truth for model provisioning, testable in Python.
- `ensure` vs `verify` separation matches `make setup-models` vs worker startup.
- Optional `sha256` hash verification catches incomplete/corrupted downloads.
- Shell scripts become one-liners, eliminating duplication.
- UpscaleEngine enables per-engine runtime validation and independent lifecycle.

### Negative

- New Python module (`app/models/`) with 6 files — more code than the shell scripts it replaces.
- `huggingface_hub` becomes a runtime dependency for model setup.
- Requires Dockerfile and docker-compose changes (new COPY for `third_party/Upscale`, new env vars).
- Breaking change: `upscale_model_dir` setting is replaced by `upscale_engine_dir` + `upscale_weights_dir`.

## Alternatives Considered

1. **Patch each shell script independently** — rejected: deepens duplication, each new model requires 3-4 script edits.
2. **YAML config-driven** — rejected: over-engineered for current model count, loses type safety.
3. **Flat ModelSetup class with hardcoded methods** — rejected: no declarative abstraction, each model requires method + ensure_all changes.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md) — `upscale_weights_dir` is the backend weight-contract root; per ADR 0003 it currently equals `MODEL_ROOT`, not a feature-grouped subdirectory.
- [Model Download Manager Design](../superpowers/specs/2026-04-25-model-download-manager-design.md)
