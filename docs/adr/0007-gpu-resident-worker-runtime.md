# ADR 0007: GPU-Resident Worker Runtime for PanoWan

Date: 2026-04-26
Status: Proposed

## Context

ADR 0001 establishes API, GPU Worker, and Model Setup as separate runtime roles. ADR 0004 defines the current queue-mediated API/Worker boundary. ADR 0006 defines `runner.py` as the canonical backend-root integration entrypoint and keeps backend execution contracts owned by project code rather than by upstream CLI shape.

Those ADRs define the role boundaries, but they do not yet decide who owns GPU-resident model state.

Today the PanoWan execution path is still effectively job-scoped. A worker claims a job, then launches a fresh execution path for inference. That means the PanoWan model stack is repeatedly reconstructed and model weights are repeatedly loaded into GPU memory. Disk-page warming tools such as `vmtouch` can reduce host I/O variability, but they do not preserve VRAM-resident model state across jobs.

The project now wants a scheduling-enhanced execution model for PanoWan:

- model residency should survive across jobs,
- workers should be able to preload and evict models deliberately,
- and future work should have a migration path toward a larger persistent inference runtime that can eventually host more than one backend family.

The main architectural choice is whether VRAM ownership should live in:

1. a separate shared residency service used by lightweight workers, or
2. the existing GPU Worker process itself.

## Decision

Adopt a **GPU-resident worker runtime** for PanoWan in version 1.

### 1. The existing GPU Worker becomes the first runtime owner

The current GPU Worker process is upgraded from a queue consumer that launches job-scoped execution into a long-lived runtime owner for PanoWan execution on its assigned GPU slot.

In version 1:

- the Worker still claims jobs from the queue,
- the Worker still owns job completion and failure reporting,
- and the Worker now also owns the long-lived PanoWan runtime state that remains resident in VRAM across jobs.

### 2. VRAM ownership is single-owner, not shared across Workers

A worker owns one GPU execution slot.

In the current deployment model, that slot normally maps to one visible GPU. In future deployments it may map to an operator-defined GPU partition such as a MIG slice or another explicit device assignment boundary. However, version 1 does not implement dynamic intra-GPU sharing between multiple Workers.

This means:

- VRAM residency is local to one Worker process,
- two Workers do not share one live PanoWan model instance,
- and cross-Worker shared residency management is deferred.

### 3. Keep the backend-root contract; change the execution lifetime behind it

`third_party/PanoWan/runner.py` remains the canonical backend-root contract surface.

However, version 1 does **not** require each job to spawn a fresh `runner.py` process. The stable contract is the payload and backend-root ownership model, not per-job process creation.

Therefore:

- the Worker may execute the same runner-owned contract through an importable backend-root adapter inside its own long-lived process,
- `runner.py --job <json>` remains the canonical CLI/debug/verification entrypoint,
- and the same validation, dispatch, and result semantics must be shared between the CLI path and the resident runtime path.

This preserves ADR 0006's ownership boundary while removing job-scoped process lifetime as an accidental performance constraint.

### 4. Version 1 supports scheduling-enhanced residency, not a generic graph runtime

Version 1 should add only the runtime-management features needed to make residency useful and operable:

- preload the PanoWan runtime before a job or through explicit warm-up,
- keep the active runtime resident across compatible jobs,
- evict the runtime intentionally on policy triggers such as idle timeout or explicit reset,
- report warm/cold/loading/failed state for scheduling and diagnostics,
- and recover from failed loads or OOMs by resetting the local runtime owner state.

Version 1 is not a node-graph execution system and is not yet a backend-generic inference host.

### 5. Defer a separate residency service until after the worker-owned runtime proves itself

Do not introduce a shared cross-Worker GPU residency service in version 1.

A separate service would add:

- another lifecycle and health surface,
- RPC semantics between Worker and runtime owner,
- shared concurrency and lease policy,
- and more complex cancellation and failure routing.

Those costs are deferred until the project has validated the worker-owned runtime shape and has concrete requirements for cross-Worker or multi-backend sharing.

## Explicit Non-Decisions

This ADR intentionally does **not** do the following in version 1:

1. Do not introduce a global GPU residency service shared by multiple Workers.
2. Do not turn Workers into purely stateless queue forwarders.
3. Do not build a ComfyUI-style node graph system.
4. Do not design a backend-generic persistent runtime host yet.
5. Do not support arbitrary multi-tenant VRAM sharing inside one GPU slot.
6. Do not replace the queue-mediated API/Worker execution path with direct API-to-runtime RPC.
7. Do not make upstream PanoWan CLI shape the long-lived product contract.

## Consequences

### Positive

- Eliminates the biggest avoidable cost in the current PanoWan path: repeated model reload into VRAM.
- Preserves the existing API/Worker queue boundary from ADR 0004.
- Keeps GPU-resident state owned by a single long-lived process, which simplifies preload, eviction, cancellation, and OOM recovery.
- Reuses the current Worker role instead of introducing a second runtime service before the residency model is proven.
- Creates a clean migration path toward a future dedicated runtime service once backend diversity or scheduling complexity justifies the split.

### Negative

- The Worker becomes a heavier process with both queue and residency responsibilities.
- A Worker crash now drops both job execution and its resident model state.
- Horizontal scaling still happens at Worker granularity, not at a separate runtime-service granularity.
- Version 1 does not allow multiple Workers to benefit from one shared live model instance.
- Future extraction of a dedicated residency service will still require a follow-up refactor.

## Alternatives Considered

1. **Keep the current job-scoped execution path and only warm host files with `vmtouch`** — rejected because host page-cache warming does not solve repeated VRAM model initialization.
2. **Make every Worker fully independent and keep process-per-job execution** — rejected because it preserves the main latency problem and offers no durable residency model.
3. **Introduce a shared GPU residency service immediately** — rejected for version 1 because it adds distributed ownership, RPC, and lease complexity before the local runtime model is validated.
4. **Build a backend-generic ComfyUI-like runtime framework immediately** — rejected because the project needs residency and scheduling gains now, not an early graph-execution abstraction.

## Relationship to Specs

This ADR records the architectural decision.

Implementation details such as preload policy, eviction triggers, Worker state transitions, queue integration, and health reporting belong in backend or runtime specs rather than in this ADR.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md)
- [ADR 0004: Worker Registry and Communication Boundary](0004-worker-registry-and-communication-boundary.md)
- [ADR 0006: Backend Runtime Input and Output Contract](0006-backend-runtime-input-and-output-contract.md)
- [PanoWan Backend Runtime Vendor Entry Design](../superpowers/specs/2026-04-26-panowan-backend-runtime-vendor-entry-design.md)
- [PanoWan Runner v1 Contract Design](../superpowers/specs/2026-04-26-panowan-runner-v1-contract-design.md)
