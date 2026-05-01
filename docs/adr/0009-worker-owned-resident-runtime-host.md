# ADR 0009: Worker-Owned Resident Runtime Host

Date: 2026-04-30
Status: Proposed

> This ADR supersedes the PanoWan-specific residency direction in ADR 0007. ADR 0007 validated the need for worker-owned GPU residency, but its version-1 scope intentionally stopped short of a backend-generic runtime host. That scope is now replaced.

## Context

ADR 0001 establishes API, Worker, and setup as separate runtime roles. ADR 0003 defines backend runtime contracts and allows backend-specific runtime isolation. ADR 0006 defines the backend-root runtime input/output contract and preserves `runner.py` as a project-owned integration surface.

The current implementation already shows that GPU residency is no longer a purely backend-local concern:

- the Worker owns preload and idle-eviction policy,
- runtime status is published through Worker telemetry,
- and engine code leaks internal controller state back into Worker orchestration.

That leakage is a symptom of the wrong abstraction boundary. The project does not merely need a better PanoWan controller. It needs a platform-owned resident runtime host that can manage backend-specific runtime providers while preserving backend-root execution contracts.

The main architectural question is no longer whether residency should exist. That was already answered by ADR 0007. The remaining question is where residency lifecycle, VRAM policy, and runtime-instance ownership belong.

## Decision

Adopt a **Worker-owned resident runtime host** as the platform execution model for resident-capable backends.

### 1. Residency is a platform capability, not a backend feature

Resident runtime lifecycle is owned by Worker platform code.

This includes:

- runtime instance ownership,
- preload,
- warm reuse,
- eviction,
- failure recovery,
- health/status reporting,
- and future runtime selection policy.

Backends may participate in residency, but they do not own residency policy.

### 2. The Worker is the runtime host owner

The existing Worker process remains the owner of:

- queue consumption,
- job ownership,
- cancellation checks,
- job completion/failure reporting,
- and Worker registry publication.

The Worker additionally owns a resident runtime host responsible for managing backend-specific runtime providers on its assigned execution slot.

Version 1 still uses one Worker as the owner of one GPU execution slot. Cross-Worker shared residency remains out of scope.

### 3. Backends provide runtime providers, not private residency controllers

A resident-capable backend must expose provider-level operations that the Worker-owned host can orchestrate.

Those operations include:

- building runtime identity from job input,
- loading a runtime instance,
- executing a job against a loaded runtime,
- tearing down a loaded runtime,
- and classifying runtime-corrupting failures.

The backend provides domain-specific execution behavior. The platform host provides lifecycle ownership.

### 4. Backend-root contracts remain stable

`runner.py` remains the canonical backend-root integration entrypoint.

However, per-job process creation is not part of the durable product contract.

Therefore:

- CLI and debug execution may continue to use `runner.py --job <json>`,
- resident execution may import and call shared backend-root adapter/provider code in-process or through a host-managed dedicated runtime,
- and both paths must share the same payload validation, dispatch, and result semantics.

The stable contract is the backend-root integration surface, not the process lifetime behind it.

### 5. Runtime environment ownership and runtime residency are separate concerns

Backend runtime contracts must distinguish between:

1. **runtime environment** — interpreter, required modules, commands, and runtime bundle shape,
2. **runtime residency participation** — whether the backend can be hosted as a resident runtime provider and how the host should load/execute/teardown it.

This separation allows the project to preserve backend-specific runtime isolation without forcing residency policy to live in backend-specific engine code.

### 6. The architecture targets multiple resident-capable backends

PanoWan is the first backend that requires this platform model, but it is not a special case in architecture vocabulary.

The project should use backend-generic host terms such as:

- resident runtime host,
- runtime provider,
- runtime identity,
- runtime instance,
- preload,
- eviction,
- and runtime status.

PanoWan-specific naming should exist only inside the PanoWan provider implementation and backend-root contract.

## Explicit Non-Decisions

This ADR does not yet do the following:

1. It does not introduce a separate cross-Worker residency service.
2. It does not require direct API-to-runtime RPC.
3. It does not require a ComfyUI-style node graph runtime.
4. It does not require arbitrary multi-tenant intra-GPU sharing within one execution slot.
5. It does not require all backends to become resident-capable.

## Consequences

### Positive

- Removes the ownership leak between Worker orchestration and backend engine internals.
- Preserves backend-root execution contracts while allowing process lifetime to evolve.
- Keeps residency policy in one platform-owned place instead of copying it into each backend.
- Creates a durable path for future resident-capable backends beyond PanoWan.
- Supports backend-specific runtime isolation without making lifecycle ownership backend-specific.

### Negative

- Requires a larger refactor than continuing the current PanoWan-specific controller path.
- Invalidates the earlier “version 1 only” boundary from ADR 0007.
- Requires backend contract and setup metadata to grow beyond simple interpreter/module checks.
- Requires Worker runtime code, engine code, and backend-root adapter code to be realigned at once.

## Alternatives Considered

1. **Keep the current PanoWan-specific runtime controller and incrementally generalize later** — rejected because it preserves the wrong ownership boundary and would keep platform concerns leaking through engine internals.
2. **Let each backend own its own residency lifecycle independently** — rejected because preload, eviction, health, and scheduling signals are Worker/platform concerns.
3. **Move immediately to a separate residency service** — rejected for now because the project still benefits from proving the platform contract inside the Worker before adding RPC and shared lease complexity.
4. **Return to process-per-job execution and optimize startup only** — rejected because it abandons the core VRAM-residency goal.

## Supersedes

- ADR 0007's PanoWan-specific residency framing and its explicit choice to avoid a backend-generic persistent runtime host in version 1.

ADR 0007 remains useful as historical context for why worker-owned residency was chosen over a separate service, but this ADR replaces ADR 0007 as the authoritative architecture direction for resident runtime ownership.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md)
- [ADR 0004: Worker Registry and Communication Boundary](0004-worker-registry-and-communication-boundary.md)
- [ADR 0006: Backend Runtime Input and Output Contract](0006-backend-runtime-input-and-output-contract.md)
- [ADR 0007: GPU-Resident Worker Runtime for PanoWan](0007-gpu-resident-worker-runtime.md)
- [Platform Resident Runtime Host Design](../superpowers/specs/2026-04-30-platform-resident-runtime-host-design.md)
