# ADR 0003: Backend Runtime Contracts

Date: 2026-04-25
Status: Proposed

## Context

ADR 0001 defines an engine-oriented product runtime: product capabilities are implemented by engines, and engines may contain backend implementations for concrete model families or algorithms.

Backends can have runtime requirements that differ from the primary application runtime. For example, a video upscale backend may require its own Python packages, system commands, model weights, or vendored inference code. Installing all optional backend dependencies into the main worker runtime would increase image size, raise dependency-conflict risk, and make optional capabilities mandatory for every worker.

The project also needs a long-lived place to record backend runtime policy. Implementation plans under `docs/superpowers/plans/` are temporary and may be cleaned up, while ADRs and specs are expected to remain maintained.

An external backend manifest was considered. A manifest would move backend metadata such as required engine files, required weight files, required commands, runtime interpreter, required modules, display name, and scale limits into backend-local configuration files.

## Decision

Define backend runtime contracts as explicit, validated metadata owned by code for now. Backend-specific details live in specs; this ADR defines the general policy.

The backend runtime contract is:

1. **Backends are implementation units under product engines**
   - Product engines expose stable capability-level contracts.
   - Backends are concrete implementations inside those engines.
   - Callers should depend on the engine/backend contract, not on upstream project internals.

2. **Backend runtime readiness must be explicit**
   - A backend declares the files, weights, commands, runtime interpreter, and import probes required to run.
   - Registered backends are not automatically available.
   - Available backends are registered backends whose declared runtime contract validates in the current environment.

3. **Backend dependencies may be isolated**
   - A backend may declare a dedicated Python runtime or other runtime boundary when its dependencies should not pollute the main worker runtime.
   - Backend dependencies must be installed during build/setup, not dynamically during job execution.
   - Runtime `pip install` or equivalent dependency mutation during a user job is not allowed.

4. **Model assets are addressed through stable model-family paths**
   - Backend specs should define stable model-family asset paths under `MODEL_ROOT`.
   - Functional grouping such as `upscale/` should not be required unless it is part of the product-level storage contract.

5. **External backend manifests are deferred**
   - Backend metadata remains Python-owned while backend count and diversity are still low.
   - Concrete backend specs may revisit manifests when multiple backend profiles are production-ready or when non-Python tooling must consume backend metadata directly.

## Example: Upscale RealESRGAN

Upscale RealESRGAN is the motivating example for this ADR.

Its current target contract is documented in the Upscale Backend Integration spec and includes:

- a backend-specific Python runtime,
- a vendored inference-only runtime bundle,
- explicit engine-file and weight-file checks,
- required command checks,
- required Python module probes,
- and model-family weights under `MODEL_ROOT`.

The exact RealESRGAN paths, entrypoint file, weight file, and module list are intentionally specified in the Upscale spec rather than in this ADR.

## Manifest Decision

Do not introduce external backend manifests at this stage.

Reasons:

1. **Backend diversity is not yet high enough** — one backend is currently the primary production target, while other backends still need separate runtime and GPU validation.
2. **Command construction remains backend-specific code** — a manifest can describe assets and dependencies, but cannot eliminate backend-specific execution logic.
3. **Python metadata is sufficient for the current scale** — typed Python metadata avoids introducing schema parsing, dynamic discovery, and config validation before they are needed.
4. **Manifest machinery has real maintenance cost** — schema design, validation, error reporting, Docker/script consumption, and tests would add complexity before clear payoff.

Revisit manifests when at least three backend profiles are production-ready, or when Docker, CI, setup tooling, or external contributors need to consume backend metadata without importing Python application code.

## Consequences

### Positive

- Keeps backend availability explicit and testable.
- Avoids dependency pollution in the main worker runtime.
- Supports optional backend profiles without requiring all workers to install all backend dependencies.
- Keeps concrete backend contracts in specs where implementation details can evolve.
- Avoids premature manifest/schema infrastructure.

### Negative

- Adding a backend still requires Python code changes.
- Backend metadata may remain split between contract constants and backend implementation classes.
- Non-Python tooling cannot read backend metadata without either importing Python code or duplicating a subset of the contract.
- Specs must be kept current with concrete backend directory and file contracts.

## Alternatives Considered

1. **Install every backend dependency into the main worker runtime** — rejected: increases conflict risk and makes optional backend dependencies mandatory for all workers.
2. **External backend manifest now** — rejected: useful later, but premature while backend diversity is low and execution logic remains Python-specific.
3. **Treat registered backends as available backends** — rejected: exposes models that may not have files, weights, commands, or runtime dependencies in the current worker.
4. **Let backends install missing dependencies at runtime** — rejected: non-deterministic, slow, hard to secure, and can mutate a running worker during a user job.
5. **Store concrete backend paths only in implementation plans** — rejected: plans are temporary; durable backend contracts belong in ADRs and specs.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0002: Unified Model Download Manager](0002-model-download-manager.md)
- [Upscale Backend Integration Design](../superpowers/specs/2026-04-25-upscale-backend-integration-design.md)
