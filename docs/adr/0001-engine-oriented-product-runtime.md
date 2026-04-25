# ADR 0001: Engine-oriented Product Runtime

Date: 2026-04-24
Status: Accepted

## Context

PanoWan Worker is moving beyond a local Dockerized service around one upstream project. Current product work includes video generation APIs, job orchestration, I2V planning, upscale integration, SSE status delivery, Web UI usage, and persistent runtime outputs.

The project should not be framed as a thin wrapper around PanoWan. PanoWan is the current default inference engine, but future product direction includes alternative engines and distributed execution across GPU workers.

The previous all-in-one container model made local startup convenient, but it mixed several responsibilities:

- API and Web UI serving.
- Job orchestration.
- GPU inference execution.
- Engine dependencies.
- Model download and validation.
- Runtime output management.

That design makes it easy to patch local issues but hard to evolve toward multi-engine execution or GPU cluster scheduling.

## Decision

Split the product runtime architecture into three explicit roles:

1. **API service** — CPU-only product API, Web UI, job creation/query/cancellation, status streaming, and scheduler or job-backend interaction.
2. **GPU Worker service** — GPU-enabled execution role that loads engine adapters, validates models, claims jobs, runs inference, writes outputs, and updates job status.
3. **Model Setup role** — repeatable one-shot asset preparation for model weights, LoRA files, upscale assets, and related validation.

Treat PanoWan as a replaceable vendor engine boundary, not as the main application boundary.

Move large model downloads out of production service startup. Production worker startup should validate required assets and fail with actionable instructions when assets are missing.

Do not preserve old all-in-one compose behavior as the default architecture. Development convenience may exist as an override or temporary workflow, but it must not define the product topology.

## Consequences

### Positive

- API images can stay lightweight and CPU-only.
- GPU dependencies are isolated to worker images.
- PanoWan can be replaced or complemented by future engines.
- Model preparation becomes explicit and repeatable.
- Docker and Compose files can express product topology instead of historical script flow.
- The architecture has a clear path toward distributed scheduling and multi-worker execution.

### Negative

- The rearchitecture is larger than a patch-level Docker fix.
- Some current all-in-one startup assumptions will be removed instead of preserved.
- API and worker communication boundaries must be made explicit even while the first backend remains local.
- Documentation, Makefile commands, scripts, and tests need to be updated together to avoid mixed architecture signals.

## Implementation Guidance

Near-term implementation should:

- Add root product runtime dependencies separately from engine dependencies.
- Build separate Docker targets for API and PanoWan worker roles.
- Replace all-purpose startup behavior with role-specific API, worker, model setup, and runtime check scripts.
- Keep PanoWan under `third_party/PanoWan` as the first engine.
- Ensure API startup does not import engine-heavy modules.
- Keep model downloads out of production worker startup.

## Implementation Notes

The initial implementation uses Dockerfile targets `api`, `worker-panowan`, `dev-api`, and `dev-worker-panowan`. The default Compose topology exposes `api`, `worker-panowan`, and a profiled `model-setup` service.

## Related Documents

- [Product Runtime Architecture](../product-runtime.md)
