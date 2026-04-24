# Docker Compose Product Runtime Rearchitecture Design

Date: 2026-04-24
Status: Draft for review

## Purpose

This design replaces the current Docker and docker-compose architecture with a product-runtime architecture for PanoWan Worker. The goal is not to patch the existing container startup flow, but to establish a clean foundation for a productized video generation platform.

The project is not a thin wrapper around PanoWan. It is evolving into a video generation product runtime with T2V, I2V, upscale, job orchestration, and eventually distributed GPU scheduling. PanoWan remains the current default inference engine, but the architecture must allow future engines to replace or coexist with it.

## Product Direction

PanoWan Worker should be treated as an early product platform with these long-term goals:

- Productized video generation API and runtime.
- Multiple capabilities: T2V, I2V, upscale, and future post-processing or generation modes.
- Replaceable inference engines, with PanoWan as the first engine.
- GPU worker execution separated from CPU API orchestration.
- A path toward distributed scheduling across a GPU cluster.

This design intentionally does not preserve the old all-in-one Docker behavior. The default topology should express the target architecture instead of preserving local historical convenience.

## Accepted Principles

1. API service is CPU-only and does not require GPU access.
2. Worker service owns GPU access, engine dependencies, and model mounts.
3. PanoWan remains a vendor engine boundary, not the application boundary.
4. Model and asset downloads are removed from the production service startup path.
5. Root project owns product runtime dependencies.
6. Engine dependencies remain isolated from API dependencies.
7. README and docs must record product vision, architecture, and decisions.
8. No backward-compatibility shims are required.

## Runtime Roles

### API Service

The API service owns the user-facing product surface:

- HTTP API.
- Job creation, query, cancellation, and status reporting.
- SSE event streaming and frontend-facing status updates.
- Input validation.
- Scheduler or job-backend interaction.

The API service must not import heavy engine modules at startup. It must not require torch, flash-attn, xformers, CUDA libraries, or PanoWan source to start.

The API image does not declare `gpus: all` and should be deployable on CPU-only nodes.

### Worker Service

The worker service owns GPU execution:

- Engine adapter loading.
- Capability registration.
- Job claiming and execution.
- Model path validation.
- Output writing.
- Job status updates.

The first worker target is `worker-panowan`, with:

- `ENGINE=panowan`
- `CAPABILITIES=t2v,i2v,upscale`
- PanoWan dependencies.
- GPU access.
- Model volume mounts.

Future workers can use the same role contract with different engines, such as SeedVR, Real-ESRGAN, RealBasicVSR, or other inference backends.

### Model Setup Service

Model setup is a separate one-shot role. It prepares model assets and can be run repeatedly.

Responsibilities:

- Download Wan model weights.
- Download PanoWan LoRA weights.
- Download or prepare upscale models.
- Validate required model files.

Production service startup does not download models. If required assets are missing, worker startup fails fast with a clear message telling the operator to run the setup command.

## Dockerfile Structure

Use one Dockerfile with role-oriented targets:

```text
runtime-base
api-deps
engine-panowan-deps
api
worker-panowan
dev-api
dev-worker-panowan
```

### runtime-base

Contains shared runtime basics:

- Python 3.13 runtime strategy.
- uv.
- common OS tools.
- optional `vmtouch` if retained.

It contains no app code, no engine source, and no model download logic.

Python 3.13 should be the product runtime baseline because PanoWan requires `>=3.13,<3.14`. Keeping API and worker on the same Python line avoids split interpreter maintenance.

### api-deps

Installs root product runtime dependencies from root `pyproject.toml` and lockfile.

Expected dependency ownership:

- fastapi
- uvicorn[standard]
- sse-starlette
- product job backend dependencies
- product API/runtime utilities

It must not install torch, flash-attn, xformers, or other engine-heavy dependencies.

### engine-panowan-deps

Installs PanoWan engine dependencies from `third_party/PanoWan/pyproject.toml` and `third_party/PanoWan/uv.lock`.

This target owns:

- torch
- torchvision
- transformers
- accelerate
- xformers
- flash-attn
- image/video libraries needed by PanoWan

This layer should maximize cache stability by only depending on PanoWan dependency manifests before source files are copied.

### api

Builds the CPU API image.

Includes:

- api-deps
- product app code
- API startup script or module

Command:

```bash
python -m app.api_service
```

Excludes:

- PanoWan source
- model files
- GPU-specific runtime assumptions

### worker-panowan

Builds the GPU worker image for the PanoWan engine.

Includes:

- product worker runtime dependencies
- engine-panowan-deps
- product app code
- `third_party/PanoWan` copied to `/engines/panowan`
- worker startup and runtime check scripts

Command:

```bash
python -m app.worker_service
```

Key environment variables:

```env
SERVICE_ROLE=worker
ENGINE=panowan
CAPABILITIES=t2v,i2v,upscale
PANOWAN_ENGINE_DIR=/engines/panowan
MODEL_ROOT=/models
RUNTIME_DIR=/app/runtime
```

### dev-api and dev-worker-panowan

Development targets add dev dependencies and bind-mount friendliness. They do not change production semantics.

`dev-api` supports reload for the API service.

`dev-worker-panowan` supports mounted product and engine source, shared uv cache, and dev-only dependency sync if needed.

## Root Python Project

Add root `pyproject.toml` for the product runtime.

The root project represents the platform, not a wrapper. It should own API, job orchestration, scheduler integration, and product runtime dependencies.

Suggested structure:

```toml
[project]
name = "panowan-worker"
requires-python = ">=3.13,<3.14"
dependencies = [
  "fastapi",
  "uvicorn[standard]",
  "sse-starlette",
]

[dependency-groups]
dev = [
  "pytest",
  "ruff",
]
```

PanoWan engine dependencies stay in `third_party/PanoWan`. They are not promoted into root dependencies because that would contaminate the API image with GPU-heavy dependencies.

## Compose Topology

Rename or replace compose files around product roles.

Recommended files:

```text
compose.yml
compose.dev.yml
```

`compose.yml` is the default split topology. `compose.dev.yml` is a development override.

### compose.yml

Services:

```text
api
worker-panowan
model-setup
```

#### api

CPU-only service.

Responsibilities:

- Expose HTTP port.
- Mount runtime state.
- Talk to job backend.
- Avoid GPU and model mounts unless strictly needed for serving files.

Representative configuration:

```yaml
api:
  build:
    context: .
    target: api
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
  depends_on:
    - worker-panowan
  restart: unless-stopped
```

#### worker-panowan

GPU service.

Representative configuration:

```yaml
worker-panowan:
  build:
    context: .
    target: worker-panowan
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
  volumes:
    - ${MODEL_ROOT:-./data/models}:/models
    - ./data/runtime:/app/runtime
  gpus: all
  restart: unless-stopped
```

#### model-setup

One-shot setup role behind a profile.

Representative configuration:

```yaml
model-setup:
  build:
    context: .
    target: worker-panowan
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

### compose.dev.yml

Development override:

- Uses `dev-api` and `dev-worker-panowan` targets.
- Bind-mounts product source.
- Bind-mounts PanoWan engine source for engine development.
- Uses a compose-managed uv cache volume.
- Enables API reload.

Representative configuration:

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

  worker-panowan:
    build:
      target: dev-worker-panowan
    environment:
      DEV_MODE: "1"
      UV_LINK_MODE: copy
    volumes:
      - ./app:/app/app
      - ./scripts:/app/scripts
      - ./third_party/PanoWan:/engines/panowan
      - ${MODEL_ROOT:-./data/models}:/models
      - ./data/runtime:/app/runtime
      - panowan-uv-cache:/root/.cache/uv

volumes:
  panowan-uv-cache:
```

Do not use an external uv cache volume by default. Compose should create it.

## Makefile Interface

Use explicit commands instead of `DEV=1` mode switching.

Recommended commands:

```text
make init
make build
make build-dev
make setup-models
make up
make up-dev
make down
make down-dev
make logs
make logs-dev
make health
make doctor
```

Expected semantics:

- `make setup-models`: runs the setup profile one-shot service.
- `make up`: starts `api` and `worker-panowan` from the production topology.
- `make up-dev`: starts `api` and `worker-panowan` with development overrides.
- `make health`: checks the API health endpoint.
- `make doctor`: diagnoses Docker, GPU, model files, and service state.

## Python Service Boundaries

Add role-specific modules:

```text
app/api_service.py
app/worker_service.py
app/jobs/
app/engines/
```

### app/api_service.py

Starts the API role.

Responsibilities:

- Configure uvicorn.
- Enable reload only in development.
- Import API routes without importing heavy engine modules.

### app/worker_service.py

Starts the worker role.

Responsibilities:

- Load job backend.
- Load engine registry.
- Register the configured engine and capabilities.
- Claim pending jobs.
- Execute jobs through an engine adapter.
- Update job status and output paths.

### app/jobs

Defines the job backend boundary.

Initial backend:

- local filesystem backend under `/app/runtime`.

Future backend:

- Redis, Postgres, message queue, or scheduler service.

The API and worker must communicate through this backend boundary, even if the first implementation is local filesystem based.

### app/engines

Defines engine abstraction.

Suggested modules:

```text
app/engines/base.py
app/engines/registry.py
app/engines/panowan.py
```

`panowan.py` owns the integration with `/engines/panowan`.

Engine interface responsibilities:

- Declare engine name.
- Declare capabilities.
- Validate model availability.
- Run a job.
- Return output metadata.

Upscale can initially be modeled as a capability adapter. If it grows independent scheduling/resource requirements, it can become a separate engine or worker type later.

## Script Boundaries

Replace the all-purpose startup script with role-specific scripts.

Recommended scripts:

```text
scripts/start-api.sh
scripts/start-worker.sh
scripts/model-setup.sh
scripts/check-runtime.sh
scripts/doctor.sh
```

### start-api.sh

Only starts the API role.

Allowed responsibilities:

- Load environment.
- Ensure runtime directories exist.
- Start `python -m app.api_service`.

Disallowed responsibilities:

- Model downloads.
- GPU checks.
- Engine dependency sync.

### start-worker.sh

Only starts the worker role.

Allowed responsibilities:

- Load environment.
- Run `check-runtime.sh`.
- Start `python -m app.worker_service`.

Disallowed responsibilities:

- Model downloads in production startup.

### model-setup.sh

Owns asset preparation.

Responsibilities:

- Download Wan weights.
- Download PanoWan LoRA.
- Download upscale models when needed.
- Validate expected files.

### check-runtime.sh

Fast runtime validation.

Checks:

- Runtime directory is writable.
- Model root exists.
- Required engine assets exist.
- Worker can see GPU if running worker role.
- Engine source path exists.

Failure message should tell the operator which setup command to run.

## Environment Model

`.env.example` should be rewritten around product concepts.

Suggested groups:

```env
# Service
HOST=0.0.0.0
PORT=8000

# Product runtime
RUNTIME_DIR=/app/runtime
JOB_BACKEND=local

# Worker
ENGINE=panowan
CAPABILITIES=t2v,i2v,upscale
MAX_CONCURRENT_JOBS=1

# Model assets
MODEL_ROOT=/models
WAN_MODEL_PATH=/models/Wan-AI/Wan2.1-T2V-1.3B
LORA_CHECKPOINT_PATH=/models/PanoWan/latest-lora.ckpt
UPSCALE_MODEL_DIR=/models/upscale

# PanoWan engine
PANOWAN_ENGINE_DIR=/engines/panowan

# Downloads
HF_TOKEN=
HF_ENDPOINT=https://hf-mirror.com
HF_MAX_WORKERS=8
HF_HUB_ENABLE_HF_TRANSFER=0

# Timeouts
GENERATION_TIMEOUT_SECONDS=1800
UPSCALE_TIMEOUT_SECONDS=1800

# Performance
PYTORCH_ALLOC_CONF=expandable_segments:True
VMTOUCH_MODELS=0
```

Compose should not define empty variables that override Python defaults.

## Documentation Updates

Documentation is part of the rearchitecture, not an afterthought.

### README

Update README with:

- Product vision.
- Current capabilities.
- Default PanoWan engine.
- Future multi-engine direction.
- Future distributed GPU scheduling direction.
- API / Worker / Model Setup architecture.
- Quick start with model setup.
- Development workflow.
- Engine model explanation.

### Architecture Doc

Add:

```text
docs/architecture/product-runtime.md
```

Contents:

- Product positioning.
- Runtime roles.
- Dependency boundaries.
- Engine adapter strategy.
- Model asset strategy.
- Local filesystem job backend as a stepping stone.
- Distributed scheduling roadmap.

### ADR

Add:

```text
docs/architecture/adr/0001-engine-oriented-product-runtime.md
```

Decision:

- Split runtime into API, GPU worker, and model setup roles.
- Keep API CPU-only.
- Keep PanoWan as replaceable engine.
- Move model downloads out of service startup.

Consequences:

- Old all-in-one compose behavior is removed.
- Docker and scripts are organized by product runtime roles.
- Future multi-engine and distributed scheduling become natural extensions.

## Validation Strategy

### Build Validation

Commands:

```bash
make build
make build-dev
```

Expected results:

- API image builds without engine-heavy dependencies.
- Worker image builds with PanoWan engine dependencies.

### Setup Validation

Command:

```bash
make setup-models
```

Expected result:

- Required model assets exist under `MODEL_ROOT`.

### Runtime Validation

Commands:

```bash
make up
make health
```

Expected results:

- API responds to health checks.
- Worker starts with GPU access.
- Missing models fail worker startup with actionable error.

### Test Validation

Run existing tests and add architecture tests.

Suggested tests:

```text
tests/test_engine_registry.py
tests/test_job_backend.py
tests/test_api_does_not_import_engine.py
```

`test_api_does_not_import_engine` should guard the CPU-only API boundary by ensuring API startup does not import known engine-heavy modules.

## Implementation Phases

1. Documentation and product positioning.
2. Root product dependency manifest.
3. Dockerfile role targets.
4. Compose topology.
5. Script split.
6. Python role entrypoints and engine/job boundaries.
7. Validation and cleanup.

Each phase should remove obsolete behavior instead of preserving compatibility shims.
