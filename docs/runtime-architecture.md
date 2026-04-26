# Runtime Architecture

Date: 2026-04-24 (renamed from `product-runtime.md` 2026-04-25)
Status: Accepted direction; Docker/Compose implementation complete; backend runtime contract codified in ADR 0003.

## Summary

PanoWan Worker is a video generation runtime composed of four layered concerns:

- **Application Architecture** — the API surface, job orchestration, runtime state, and event delivery that operators and clients interact with.
- **Engine Architecture** — the per-capability boundary (`PanoWanEngine`, `UpscaleEngine`, …) that owns capability registration, runtime validation, and routing into a backend.
- **Worker Runtime** — the per-engine process(es) that claim jobs, execute inference on GPU, and write outputs.
- **Backend Runtime Contract** — the deterministic asset/file/CLI/python-import surface a backend must satisfy to be available, codified in ADR 0003.

The current default generation engine is `PanoWanEngine`; `UpscaleEngine` ships with the `RealESRGANBackend` as the first concrete backend. The architecture is engine-oriented and worker-oriented: API and GPU execution are separated so the system can grow from a single-machine local runtime into a multi-engine platform and eventually a distributed GPU scheduling system.

## Application Architecture

The application layer owns product interaction and orchestration entry points.

Responsibilities:

- HTTP API and Web UI serving.
- Job creation, listing, lookup, cancellation, and status reporting.
- SSE event delivery.
- Request validation and rejection of jobs that target unavailable backends (per ADR 0003).
- Interaction with the job backend or scheduler.

The API service is CPU-only. It does not require CUDA, torch, flash-attn, xformers, PanoWan source, or model files to start.

### Model Setup

Model setup is a one-shot asset preparation role at the application layer.

Responsibilities:

- Download and validate Wan model weights.
- Download and validate PanoWan LoRA weights.
- Download and sha256-verify backend weights (e.g. `Real-ESRGAN/realesr-animevideov3.pth`) under `MODEL_ROOT`.
- Ensure the asset surface declared by the active backend runtime contracts exists before workers are expected to run.

Production service startup does not perform large model downloads. Missing assets produce actionable failures that direct operators to run the setup flow.

## Engine Architecture

An **engine** is the product-owned boundary between the application and one or more backends. Each engine declares the capabilities it supports, validates its runtime, and routes jobs to a concrete backend.

Responsibilities:

- Declare engine name and supported capabilities (T2V, I2V, upscale, …).
- Translate product jobs into backend-specific calls.
- Refuse to start when no backend is available (`UpscaleEngine.validate_runtime()`).
- Return output metadata in a product-owned format.

PanoWan remains under `third_party/PanoWan` as a vendor engine. New capabilities should be added behind the engine boundary instead of becoming new application roots.

## Worker Runtime

The worker runtime is the per-engine process that owns inference execution.

Responsibilities:

- Claim pending jobs from the job backend.
- Load the configured engine adapter.
- Validate model and runtime assets before accepting work.
- Execute T2V, I2V, upscale, or future capabilities.
- Write outputs.
- Update job status and result metadata.

Workers are specialized by engine. The first worker type is `worker-panowan`, hosting `PanoWanEngine` and `UpscaleEngine`.

## Backend Runtime Contract

A **backend** is the concrete implementation behind an engine (e.g. `RealESRGANBackend` behind `UpscaleEngine`). Per [ADR 0003](adr/0003-backend-runtime-contract.md), every backend declares a deterministic runtime contract through `UpscaleBackendAssets` (or its engine equivalent):

- **Engine files** rooted at the runtime layout's canonical engine root (`/engines/upscale` in containers, `third_party/Upscale` on the host) — vendored runtime files copied from `third_party/<bundle>/` at build time, with each backend living under its own subtree such as `realesrgan/`, `realbasicvsr/`, or `seedvr2/`.
- **Weight files** rooted at `MODEL_ROOT` (currently `/models` in containers) — backend weights live under `/models/<MODEL_FAMILY>/`, e.g. `/models/Real-ESRGAN/realesr-animevideov3.pth`.
- **Required commands** on `PATH` (e.g. `ffmpeg`).
- **Runtime Python** at a backend-isolated path (e.g. `/opt/venvs/upscale-realesrgan/bin/python`).
- **Required Python modules** that the runtime Python must import.

A backend is considered **available** only when every contract clause holds. The contract is the single source of truth: `app/upscale_contract.py` exports the file lists and the family/filename atoms, `app/paths.py` owns the canonical roots and derived path atoms, and `app/settings.py` derives runtime paths from that layout instead of exposing leaf-path environment variables. `RealESRGANBackend.build_command()`, `app/models/specs.py`, startup scripts, and the test suite consume those Python-owned paths rather than re-spelling them.

Operator-facing configuration is intentionally smaller than the internal path graph. Compose and `.env` should expose root inputs and behavior toggles such as `SERVICE_ROLE`, `MODEL_ROOT`, `HOST`, `PORT`, concurrency, timeouts, and Hugging Face download settings. Leaf paths like `WAN_MODEL_PATH`, `LORA_CHECKPOINT_PATH`, `OUTPUT_DIR`, `JOB_STORE_PATH`, `WORKER_STORE_PATH`, `UPSCALE_ENGINE_DIR`, and `UPSCALE_OUTPUT_DIR` are internal derived values, not primary deployment knobs.

This ownership split is deliberate: Python settings own path semantics, Compose owns role and mount contracts, and shell scripts remain thin bootstrap/diagnostic layers.

## Dependency Boundaries

The root project owns application-runtime dependencies:

- FastAPI and HTTP runtime dependencies.
- Job orchestration and scheduler integration dependencies.
- Application API and worker service dependencies.

Engine and backend dependencies remain isolated:

- PanoWan owns torch, xformers, flash-attn, transformers, and other heavy generation dependencies.
- API images do not install engine-heavy dependencies.
- Backend dependencies (e.g. RealESRGAN's `cv2` / `ffmpeg-python` / `tqdm`) install into per-backend virtual environments under `/opt/venvs/<backend>/` at build time, never at job time.

This boundary keeps the API image lightweight and makes future engine/backend replacement practical.

## Model Asset Strategy

Model assets are runtime data, not application code.

Principles:

- Model weights do not belong in the Git repository.
- Model weights are not baked into the default API image.
- Model setup is explicit and repeatable.
- Workers mount model storage and validate the backend runtime contract before accepting work.
- Outputs and job state live in runtime storage.
- Per ADR 0003, `UPSCALE_WEIGHTS_DIR` defaults to `MODEL_ROOT`; backends address weights as `<MODEL_FAMILY>/<filename>` rather than `/models/upscale/<backend>/...`.

The current local implementation uses `data/models` and `data/runtime`. Future deployments can map these concepts to shared volumes, object storage, databases, or cluster-local caches.

## Job Backend Evolution

The first implementation uses a local filesystem job backend to keep the runtime simple while boundaries are introduced.

Target direction:

```text
API service
  -> job backend / scheduler
  -> GPU worker runtime
  -> job backend status updates
  -> API event stream / polling
```

Evolution path:

1. Local filesystem job backend for single-node development.
2. Explicit API/worker process separation using the same backend boundary.
3. Redis, Postgres, message queue, or scheduler-backed job coordination.
4. Multi-worker GPU scheduling with engine and capability registration.

The API and worker communicate through the backend boundary even before a distributed backend exists.

## Docker and Compose Topology

The Docker/Compose topology expresses the runtime roles:

```text
api
worker-panowan
model-setup
```

Role expectations:

- `api`: CPU-only, application API dependencies, no engine-heavy runtime.
- `worker-panowan`: GPU-enabled, PanoWan engine dependencies, model mounts, satisfies the backend runtime contracts of every active backend (currently `RealESRGANBackend`).
- `model-setup`: one-shot asset preparation that satisfies the contract's weight surface under `MODEL_ROOT`.

Development overrides may bind-mount source and enable reload, but development convenience does not define the production architecture.

## Implementation Note

The Docker/Compose implementation matches this architecture:

- `docker-compose.yml` — production split topology (api / worker-panowan / model-setup).
- `docker-compose-dev.yml` — dev override (mounts source, dev targets).
- Dockerfile role targets: `api`, `worker-panowan`, `dev-api`, `dev-worker-panowan`.
- `app/upscale_contract.py` — single-source backend runtime contract surface.

## Non-Goals

This architecture does not require implementing a full distributed scheduler immediately.

It also does not require absorbing PanoWan source into the root project. PanoWan stays behind a vendor engine boundary while the platform evolves around it.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](adr/0001-engine-oriented-product-runtime.md)
- [ADR 0002: Model Download Manager](adr/0002-model-download-manager.md)
- [ADR 0003: Backend Runtime Contracts](adr/0003-backend-runtime-contract.md)
- [Upscale Backend Integration Design](superpowers/specs/2026-04-25-upscale-backend-integration-design.md)
- [PanoWan architecture analysis](panowan-architecture.md)
