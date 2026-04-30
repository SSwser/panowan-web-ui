# PanoWan GPU-Resident Worker Runtime Design

> Superseded by [Platform Resident Runtime Host Design](2026-04-30-platform-resident-runtime-host-design.md).
>
> This document remains useful as migration history for the original PanoWan-specific resident-runtime design. It is no longer the authoritative final-state implementation target.

> Original target: upgrade the existing GPU Worker into a long-lived PanoWan runtime owner that keeps compatible model state resident in VRAM across jobs and supports explicit preload / eviction behavior.

This document defined the implementation-level design that followed ADR 0007. The active architecture direction now follows [ADR 0009: Worker-Owned Resident Runtime Host](../../adr/0009-worker-owned-resident-runtime-host.md), and the active implementation target is the platform-level resident runtime host design.

## 1. Goal and Non-Goals

### Goal

Introduce a scheduling-enhanced PanoWan worker runtime such that:

- the Worker process can keep the active PanoWan runtime resident across jobs,
- compatible jobs can reuse a warm runtime without reloading the model stack into VRAM,
- the Worker can intentionally preload, evict, and reset local runtime state,
- and the existing queue-mediated API/Worker architecture remains intact.

### Non-Goals

Version 1 does not:

- introduce a separate shared residency service,
- introduce a graph-execution runtime,
- implement backend-generic multi-runtime scheduling,
- implement arbitrary multi-tenant intra-GPU sharing,
- or replace queue-mediated execution with direct API-to-runtime RPC.

## 2. Why the Current Path Is Too Expensive

Today the Worker is long-lived, but PanoWan execution is effectively job-scoped because inference is launched through a fresh execution path per job. That means the Worker process survives, but the loaded model state does not.

This is the wrong lifetime boundary for GPU-heavy inference.

The main cost is not only filesystem I/O. The repeated cost includes:

- pipeline reconstruction,
- model graph initialization,
- moving weights into GPU memory,
- allocator warm-up,
- and repeated device residency setup.

Host file cache tools such as `vmtouch` may reduce cold reads from disk, but they do not preserve VRAM-resident state and therefore do not solve the dominant repeated startup cost.

## 3. Design Summary

Version 1 upgrades the Worker into a PanoWan runtime owner.

The Worker keeps owning:

- job claiming,
- cancellation checks,
- job completion / failure updates,
- and Worker heartbeat publication.

The Worker additionally owns:

- a long-lived PanoWan runtime controller,
- the currently resident runtime state,
- preload / evict / reset transitions,
- and warm/cold status reporting for scheduling and diagnostics.

The backend-root ownership model from ADR 0006 remains unchanged:

- `third_party/PanoWan/runner.py` remains the canonical backend-root contract entrypoint,
- backend-root adapter code remains the source of truth for runtime validation and dispatch semantics,
- and the Worker should call shared backend-root adapter code rather than rebuilding backend knowledge in `app/`.

## 4. Runtime Ownership Boundary

### 4.1 Who owns queue state

Queue state remains worker-owned.

The Worker still:

- claims the next job,
- decides whether it still owns that job,
- and writes the final status transition.

### 4.2 Who owns VRAM state

VRAM state is owned by one Worker process for one GPU execution slot.

In version 1, that slot is local to the Worker and is not shared across Workers.

### 4.3 Why version 1 should not split out a service yet

A separate residency service would require:

- request/response protocol design,
- runtime health and lease semantics,
- shared cancellation rules,
- runtime selection rules,
- and more complicated crash/failover behavior.

Version 1 does not need that extra boundary to validate the core residency design.

## 5. Proposed Internal Components

### 5.1 Worker-side runtime controller

Add a Worker-local runtime controller responsible for residency lifecycle.

Suggested responsibility set:

- expose `ensure_loaded()` for warm-up,
- expose `run_job(job_payload)` for execution on the resident runtime,
- expose `evict()` for intentional unload,
- expose `reset_after_failure()` for corrupted or OOM state,
- expose `status_snapshot()` for warm/cold/loading/failed telemetry.

The controller should be worker-owned orchestration code, not backend-specific pipeline code.

### 5.2 Backend-root shared runtime adapter

Move backend-specific execution semantics behind backend-root project-owned code under `third_party/PanoWan/`.

The adapter should own:

- contract validation,
- task dispatch (`t2v` / `i2v`),
- runtime construction,
- compatible-job checks,
- and model/runtime teardown logic.

The Worker should not become the new place where backend internals are reconstructed.

### 5.3 Resident runtime instance

The actual loaded runtime instance should be a long-lived in-process object graph containing:

- the loaded PanoWan/Wan runtime,
- references to model/pipeline objects,
- current loaded identity metadata,
- and execution compatibility metadata.

This object graph is the thing that stays warm across jobs.

## 6. Required Runtime State Model

Version 1 should use a small explicit state machine.

### States

- `cold` — nothing resident
- `loading` — runtime is being constructed
- `warm` — runtime is loaded and ready for compatible jobs
- `running` — runtime is currently executing a job
- `evicting` — runtime is unloading or resetting
- `failed` — runtime entered an unrecoverable state and must be reset before reuse

### Required transitions

- `cold -> loading -> warm`
- `warm -> running -> warm`
- `warm -> evicting -> cold`
- `running -> failed`
- `failed -> evicting -> cold`
- `cold -> loading -> failed`

The state machine should be explicit in code and testable.

## 7. Compatibility Rules for Reuse

Warm reuse is only correct for compatible jobs.

Version 1 should define compatibility narrowly to avoid accidental stale-state bugs.

At minimum, compatibility should require that:

- the same backend family is being used,
- the same model family/runtime identity is being used,
- the same LoRA/runtime configuration is being used,
- and the same device slot is still owned by the current Worker.

Version 1 does not need to reload for every difference in prompt or output path. Those are job inputs, not runtime identity.

The reuse rule should therefore compare runtime identity metadata, not whole job payload equality.

## 8. Preload and Eviction Policy

### 8.1 Preload

Version 1 preload options should be simple:

1. **startup preload** — Worker warms the default PanoWan runtime during startup after validation,
2. **lazy first-job preload** — Worker loads the runtime only when the first compatible job arrives,
3. **explicit warm-up action** — optional future control-plane trigger.

Recommended version 1 default:

- use lazy first-job preload,
- optionally allow startup preload by configuration.

This avoids forcing every Worker startup to pay the load cost even when no PanoWan jobs arrive, while still keeping the warm path available after the first load.

### 8.2 Eviction

Version 1 should support deliberate eviction through simple triggers only:

- explicit worker-side reset action,
- runtime failure / OOM recovery,
- configurable idle timeout,
- process shutdown.

Do not implement complex cross-model LRU or multi-runtime budget arbitration in version 1.

## 9. Failure and Recovery Rules

### 9.1 OOM or load failure

If runtime construction or execution fails due to OOM or another runtime-corrupting failure:

- mark the runtime state `failed`,
- do not attempt to reuse the current resident instance,
- perform explicit teardown/reset,
- and return to `cold` before any retry or next job.

### 9.2 Job failure vs runtime failure

A job can fail without invalidating the resident runtime.

Examples that should not automatically poison the runtime:

- invalid prompt payload,
- bad input path,
- output write failure,
- user cancellation.

Examples that likely should poison the runtime in version 1:

- CUDA OOM during runtime use,
- corrupted backend/pipeline state,
- runtime construction failure after partial GPU initialization.

Version 1 should be conservative: if the implementation cannot prove the runtime is still safe, reset it.

## 10. Worker Registry and Scheduling Signals

The Worker Registry should eventually expose enough state for schedulability and observability.

Version 1 does not need a full scheduler redesign, but it should prepare for it by publishing runtime status such as:

- `panowan_runtime_status`: `cold` / `loading` / `warm` / `running` / `failed`
- `panowan_runtime_identity`: optional stable identifier for the currently loaded runtime
- `panowan_runtime_last_used_at`: timestamp for idle eviction decisions

This is diagnostic and future-scheduling metadata. It does not replace worker-side execution-time validation.

## 11. Relationship to `runner.py` and the v1 Contract

The runner contract work and the resident runtime work must converge rather than fork.

Required rule:

- the Worker-resident execution path and the CLI `runner.py --job <json>` path must share one backend-root validation and dispatch implementation.

That means:

- `runner.py` remains the canonical contract/debug entrypoint,
- but `runner.py` should become a thin shell over importable adapter code,
- and the Worker-resident path should call the same adapter code in-process.

This is required so the project does not create:

1. one contract for CLI mode, and
2. another contract for the warm in-process path.

## 12. Version 1 File/Module Direction

This spec does not lock exact filenames, but version 1 should roughly converge on:

- worker-side runtime ownership code under `app/` because Worker lifecycle lives there,
- backend-specific adapter/runtime code under `third_party/PanoWan/sources/` because backend execution semantics belong to the backend root,
- and a thin backend-root `runner.py` shell that delegates into that shared adapter.

A likely split is:

- `app/worker_runtime.py` or similar for Worker-owned residency orchestration,
- `third_party/PanoWan/sources/runtime_adapter.py` for backend-root contract validation and dispatch,
- `third_party/PanoWan/sources/resident_runtime.py` for backend-specific loaded runtime lifecycle.

## 13. Version 1 Testing Strategy

### 13.1 State machine tests

Test the controller state transitions explicitly:

- cold start to warm,
- warm reuse,
- idle eviction,
- failure reset,
- running to failed transitions.

### 13.2 Compatibility tests

Verify that:

- compatible jobs reuse the warm runtime,
- incompatible runtime identity changes trigger unload/reload,
- and prompt/output-only changes do not trigger reload.

### 13.3 Worker integration tests

Verify that:

- claimed jobs run through the resident runtime owner,
- completion/failure semantics remain unchanged at the queue boundary,
- cancellation still works,
- and warm runtime state is preserved across sequential jobs.

### 13.4 Contract consistency tests

Verify that:

- CLI `runner.py --job` and in-process resident execution use the same validation rules,
- required `negative_prompt` behavior remains identical,
- and `t2v` / `i2v` dispatch rules remain runner-owned rather than worker-owned.

## 14. What Version 1 Explicitly Avoids

Version 1 should not:

- create a second worker-to-runtime RPC boundary,
- expose backend internals directly to API,
- introduce a graph scheduler,
- implement multi-backend shared VRAM budgeting,
- or optimize for more than one resident backend family at once.

These are future extensions only after the worker-owned runtime shape is validated in production-like usage.

## 15. Recommended Next Implementation Scope

The first implementation slice should be narrow:

1. make backend-root runner logic importable,
2. add a Worker-local runtime controller,
3. keep one resident PanoWan runtime per Worker,
4. support lazy load + warm reuse + explicit reset,
5. keep queue semantics unchanged,
6. and publish minimal runtime status in the Worker Registry.

That is enough to validate the architecture without prematurely introducing a shared runtime service.
