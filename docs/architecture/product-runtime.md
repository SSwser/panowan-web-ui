# Product Runtime Architecture

Date: 2026-04-24
Status: Accepted direction, implementation pending

## Summary

PanoWan Worker is evolving from a local Dockerized generation service into a productized video generation runtime. The current default inference engine is PanoWan, but the main project is the product platform: API, job orchestration, runtime state, engine integration, and the future scheduling layer.

The architecture direction is engine-oriented and worker-oriented. API and GPU execution should be separated so the project can grow from a single-machine local runtime into a multi-engine platform and eventually a distributed GPU scheduling system.

## Product Vision

The long-term product goals are:

- Provide a stable video generation API and runtime.
- Support multiple capabilities: T2V, I2V, upscale, and future generation or post-processing modes.
- Keep inference engines replaceable and composable.
- Treat PanoWan as the first engine, not the application boundary.
- Separate CPU orchestration from GPU execution.
- Evolve toward distributed scheduling across GPU workers.

## Runtime Roles

### API Service

The API service owns product interaction and orchestration entry points.

Responsibilities:

- HTTP API and Web UI serving.
- Job creation, listing, lookup, cancellation, and status reporting.
- SSE or other event delivery mechanisms.
- Request validation.
- Interaction with the job backend or scheduler.

The API service should be CPU-only. It should not require CUDA, torch, flash-attn, xformers, PanoWan source, or model files to start.

### GPU Worker

The worker service owns inference execution.

Responsibilities:

- Claim pending jobs from the job backend.
- Load the configured engine adapter.
- Validate model and runtime assets.
- Execute T2V, I2V, upscale, or future capabilities.
- Write outputs.
- Update job status and result metadata.

Workers may be specialized by engine or capability. The first worker type is expected to be `worker-panowan`, using PanoWan as the default engine.

### Model Setup

Model setup is a one-shot asset preparation role.

Responsibilities:

- Download and validate Wan model weights.
- Download and validate PanoWan LoRA weights.
- Prepare upscale model assets.
- Ensure model files exist before workers are expected to run.

Production service startup should not perform large model downloads. Missing assets should produce actionable failures that tell operators to run the setup flow.

### Engine Adapter

An engine adapter isolates product code from a specific inference implementation.

Responsibilities:

- Declare engine name and supported capabilities.
- Translate product jobs into engine-specific calls.
- Validate engine-specific model paths.
- Return output metadata in a product-owned format.

PanoWan remains under `third_party/PanoWan` as a vendor engine. Future engines should be added behind the same boundary instead of becoming new application roots.

## Dependency Boundaries

The root project owns product runtime dependencies:

- FastAPI and HTTP runtime dependencies.
- Job orchestration and scheduler integration dependencies.
- Product API and worker service dependencies.

Engine dependencies remain isolated:

- PanoWan owns torch, xformers, flash-attn, transformers, and other heavy model dependencies.
- API images should not install engine-heavy dependencies.
- Worker images combine product worker code with the selected engine dependencies.

This boundary keeps the API image lightweight and makes future engine replacement practical.

## Model Asset Strategy

Model assets are runtime data, not application code.

Principles:

- Model weights do not belong in the Git repository.
- Model weights should not be baked into the default API image.
- Model setup should be explicit and repeatable.
- Workers mount model storage and validate assets before accepting work.
- Outputs and job state live in runtime storage.

The current local implementation uses `data/models` and `data/runtime`. Future deployments can map these concepts to shared volumes, object storage, databases, or cluster-local caches.

## Job Backend Evolution

The first implementation can use a local filesystem job backend to keep the product runtime simple while boundaries are introduced.

Target direction:

```text
API service
  -> job backend / scheduler
  -> GPU worker
  -> job backend status updates
  -> API event stream / polling
```

Evolution path:

1. Local filesystem job backend for single-node development.
2. Explicit API/worker process separation using the same backend boundary.
3. Redis, Postgres, message queue, or scheduler-backed job coordination.
4. Multi-worker GPU scheduling with engine and capability registration.

The API and worker should communicate through the backend boundary even before a distributed backend exists.

## Docker and Compose Direction

The target Docker/Compose topology should express product roles:

```text
api
worker-panowan
model-setup
```

Role expectations:

- `api`: CPU-only, product API dependencies, no engine-heavy runtime.
- `worker-panowan`: GPU-enabled, PanoWan engine dependencies, model mounts.
- `model-setup`: one-shot model asset preparation.

Development overrides may bind-mount source and enable reload, but development convenience should not define the production architecture.

## Non-Goals

This architecture does not require implementing a full distributed scheduler immediately.

It also does not require absorbing PanoWan source into the root project. PanoWan should stay behind a vendor engine boundary while the product platform evolves around it.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](adr/0001-engine-oriented-product-runtime.md)
- [PanoWan architecture analysis](../panowan-architecture.md)
