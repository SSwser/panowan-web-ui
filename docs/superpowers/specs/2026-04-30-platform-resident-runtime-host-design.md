# Platform Resident Runtime Host Design

> Final implementation target: replace the PanoWan-specific resident controller path with a Worker-owned platform runtime host that manages backend-specific resident runtime providers and their runtime environments.

This document follows ADR 0009. The ADR records the architectural decision. This spec defines the implementation contract for the first platform-level resident runtime host and for migrating PanoWan onto that contract.

## 1. Goal and Non-Goals

### Goal

Introduce a platform-owned resident runtime host such that:

- the Worker owns runtime lifecycle and VRAM residency policy,
- resident-capable backends plug in as runtime providers,
- backend-root execution contracts remain stable,
- and backend-specific runtime isolation can coexist with platform-owned lifecycle management.

### Non-Goals

This design does not:

- introduce a separate cross-Worker residency service,
- introduce a graph-execution runtime,
- require all backends to become resident-capable,
- require direct API-to-runtime RPC,
- or preserve backward compatibility with the current PanoWan-specific controller architecture.

## 2. Why the Current Shape Must Be Replaced

The current implementation mixes three different responsibility layers:

1. engine-level capability routing,
2. Worker-level residency orchestration,
3. backend-specific runtime construction and execution.

That mixing appears in multiple ways:

- the PanoWan engine owns a residency controller,
- the Worker inspects that controller directly for preload, telemetry, and idle eviction,
- and a separate subprocess-based `python runner.py` execution path still exists as a product execution path.

This shape creates the wrong source of truth for lifecycle ownership.

The platform needs one host-level abstraction for:

- runtime state,
- runtime identity and warm-compatibility checks,
- preload and eviction policy,
- runtime failure recovery,
- and runtime status telemetry.

Those concerns should not live inside a backend-specific engine class.

## 3. Design Summary

The Worker owns a `ResidentRuntimeHost`.

The host manages one or more `RuntimeProvider` implementations. A provider is backend-specific. The host is platform-owned.

High-level model:

- Worker owns queue/job lifecycle.
- Worker asks the host to prepare, execute, evict, and report status.
- Host owns runtime-instance lifecycle.
- Provider owns backend-specific load/execute/teardown logic.
- Backend-root integration code remains the durable contract surface shared by CLI/debug and resident execution.

## 4. Target Internal Architecture

### 4.1 `ResidentRuntimeHost`

The host is a Worker-owned platform service.

Responsibilities:

- register resident-capable providers,
- hold runtime instance state per provider/runtime slot,
- compute or request runtime identity,
- load a runtime instance on demand,
- reuse a compatible warm instance,
- evict on explicit or policy triggers,
- mark failed/corrupt runtime state,
- and expose status snapshots for Worker telemetry and diagnostics.

The host must be the only place that owns runtime lifecycle policy.

### 4.2 `RuntimeProvider`

A provider is the backend-specific adapter contract consumed by the host.

Required operations:

- `provider_key()` or equivalent stable identity,
- `runtime_identity_from_job(job)`,
- `load(identity)`,
- `execute(loaded_runtime, job)`,
- `teardown(loaded_runtime)`,
- `classify_failure(exc)`.

Optional operations may include:

- `default_identity()` for startup preload,
- `describe_resources(identity)` for future VRAM budgeting,
- `healthcheck(loaded_runtime)`.

The provider does not own preload/evict policy. It only exposes backend-specific behavior.

### 4.3 `RuntimeInstance`

A runtime instance is the loaded resident object graph held by the host.

It must carry at least:

- provider key,
- runtime identity,
- loaded backend/runtime object,
- host-visible state,
- and last-used metadata.

The exact loaded object type remains provider-specific.

### 4.4 `Engine`

The engine remains the capability-facing execution adapter used by the Worker job loop.

Responsibilities after refactor:

- validate job-level payload shape,
- select the relevant provider/runtime key,
- delegate execution to the host,
- map provider results into `EngineResult`.

The engine must not own a private residency controller.

## 5. Runtime State Model

The host must expose one explicit state machine per runtime instance.

### States

- `cold`
- `loading`
- `warm`
- `running`
- `evicting`
- `failed`

### Required transitions

- `cold -> loading -> warm`
- `warm -> running -> warm`
- `warm -> evicting -> cold`
- `running -> failed`
- `failed -> evicting -> cold`
- `cold -> loading -> failed`

### Rules

- Only the host can mutate lifecycle state.
- Providers may signal failure classification, but they do not directly mutate host policy.
- Host state must be testable without depending on a full GPU runtime.

## 6. Runtime Identity and Compatibility

Warm reuse must be based on runtime identity, not whole-job equality.

The provider is responsible for deriving runtime identity from job inputs.

Runtime identity should capture only factors that affect loaded resident state, such as:

- backend/provider family,
- model family or checkpoint identity,
- LoRA/runtime configuration,
- and any other provider-defined parameter that changes the loaded runtime graph.

Runtime identity should not include ordinary per-job fields such as:

- prompt text,
- output path,
- or job id.

The host should evict and reload whenever the requested identity differs from the currently loaded one.

## 7. Backend Runtime Contract Extensions

The current backend contract is sufficient for setup-time bundle shape and basic runtime readiness checks, but it is too weak to describe resident-host participation.

The backend contract must distinguish:

1. runtime environment contract,
2. resident provider contract.

### 7.1 Runtime environment contract

The existing runtime section remains responsible for:

- interpreter path,
- required commands,
- required Python modules,
- and already-materialized runtime bundle assumptions.

### 7.2 Resident provider contract

Add a new backend-local contract section for resident-host participation.

Suggested fields:

- whether resident hosting is supported,
- provider key,
- load entrypoint,
- execute entrypoint,
- teardown entrypoint,
- runtime identity entrypoint,
- failure-classifier entrypoint,
- startup preload default,
- idle-eviction policy hints,
- resource-class metadata.

Field names may change during implementation, but the contract must make provider wiring declarative enough that the Worker platform code does not hardcode backend-private entrypoints.

## 8. Runtime Environment Strategy

Resident lifecycle ownership and runtime-environment isolation are separate concerns.

This design allows two implementation strategies:

1. **in-process host runtime** — the Worker process itself imports and holds the loaded provider runtime,
2. **host-managed dedicated runtime** — the Worker-owned host manages a dedicated backend runtime boundary such as a backend-specific Python environment or resident sidecar.

The architecture must not assume that all resident providers share the Worker's primary application environment.

For heavy GPU backends such as PanoWan, the preferred long-term target is a host-managed dedicated runtime boundary so that:

- heavy ML dependencies do not have to define the primary app runtime,
- backend-specific interpreter isolation remains valid,
- and future resident-capable backends can coexist without flattening all dependencies into one Worker environment.

The first implementation may use the simplest boundary that preserves the contract, but the host/provider design must not preclude a dedicated-runtime model.

## 9. Relationship to `runner.py`

`runner.py` remains the canonical backend-root integration entrypoint.

However, it is no longer the required product execution lifetime model.

Required rule:

- CLI/debug execution and resident-host execution must share the same backend-root validation and dispatch semantics.

That means:

- `runner.py --job <json>` remains valid for direct invocation and debugging,
- resident execution may call the same underlying adapter/provider code without spawning a new process per job,
- and backend-root code remains the source of truth for payload/result contract semantics.

## 10. Worker Integration Changes

### 10.1 Worker service responsibilities

The Worker service should:

- build the host,
- register available resident providers,
- publish host-owned runtime status,
- optionally preload through the host,
- optionally idle-evict through the host,
- and use engines only for job-level execution delegation.

### 10.2 Remove engine-internal runtime inspection

Worker code must stop reaching into engine-private residency state.

Patterns to remove:

- engine-owned private controller access,
- provider-specific status reads from Worker orchestration,
- provider-specific preload logic embedded directly in Worker service.

### 10.3 Telemetry and registry

Telemetry should become host-owned and provider-keyed.

At minimum, the Worker registry should be able to expose:

- runtime status,
- loaded runtime identity,
- last-used timestamp,
- and possibly provider/resource-class metadata.

## 11. PanoWan Migration Contract

PanoWan is the first backend to migrate to the new contract.

### 11.1 What must change

- Replace `PanoWanRuntimeController` with platform host abstractions.
- Move PanoWan-specific load/execute/teardown behavior behind a provider contract.
- Remove Worker dependence on PanoWan engine internals.
- Remove the subprocess `python runner.py` path as the main product execution path.

### 11.2 What remains stable

- backend-root ownership,
- PanoWan payload/result semantics,
- `runner.py` as CLI/debug surface,
- Worker ownership of queue and final job state.

### 11.3 What must be deleted, not wrapped

Because this redesign does not prioritize backward compatibility, the refactor should delete obsolete ownership paths instead of layering compatibility wrappers around them.

Delete or retire:

- PanoWan-specific residency ownership in engine code,
- Worker logic that reaches into engine-private runtime state,
- per-job subprocess execution as the default product path for PanoWan.

## 12. Failure and Recovery Rules

The host must distinguish:

- job-scoped failures,
- runtime-corrupting failures.

### Job-scoped failures

Examples:

- invalid prompt input,
- bad source path,
- output write failure,
- user cancellation.

These should fail the job without necessarily invalidating the warm runtime.

### Runtime-corrupting failures

Examples:

- CUDA OOM,
- partial runtime initialization failure,
- provider-defined unrecoverable runtime corruption.

These should transition the runtime instance to `failed` and require host-owned reset/eviction before reuse.

## 13. Testing Strategy

### 13.1 Host unit tests

Test the host state machine without GPU dependencies:

- cold load,
- warm reuse,
- identity mismatch reload,
- idle eviction,
- failed-state reset,
- corrupting vs non-corrupting failure behavior.

### 13.2 Provider contract tests

Test that provider implementations:

- build runtime identity correctly,
- load and tear down expected runtime objects,
- classify failures correctly,
- and preserve shared payload/result semantics with the CLI runner path.

### 13.3 Worker integration tests

Test that the Worker:

- publishes host status,
- preloads through host APIs,
- evicts through host APIs,
- and never depends on engine-private residency internals.

### 13.4 Backend contract tests

Test that backend metadata parsing and validation support resident-provider configuration cleanly.

## 14. Implementation Phases

### Phase A — contract realignment

- add ADR 0009,
- add this platform spec,
- extend backend contract schema for resident providers,
- update parsing and validation tests.

### Phase B — host abstraction

- replace the current backend-specific controller with `ResidentRuntimeHost`,
- define provider interfaces,
- move runtime lifecycle state into host-owned abstractions.

### Phase C — PanoWan provider migration

- implement the PanoWan provider,
- move load/execute/teardown/identity/failure-classifier behavior behind provider code,
- simplify the PanoWan engine to host delegation.

### Phase D — Worker rewiring and deletion of obsolete paths

- rewire Worker preload/evict/status through the host,
- delete engine-private runtime inspection,
- delete PanoWan subprocess execution as the main product path.

### Phase E — verification

- run host, Worker, engine, and backend contract tests,
- verify runner/debug semantics still match resident execution semantics,
- verify documented ownership boundaries match implemented code paths.

## 15. Open Decisions to Resolve During Implementation

1. Whether the first host implementation should be in-process or immediately use a dedicated backend runtime boundary.
2. Exactly which resident-provider fields should live in `backend.toml` versus code registration.
3. Whether Worker telemetry should publish only one active runtime slot or a provider-keyed map for future extensibility.
4. How far startup preload should remain configuration-driven versus provider-default-driven.

## 16. Relationship to Replaced Documents

This spec replaces the PanoWan-specific resident-runtime design as the primary implementation target.

Older PanoWan-specific runtime documents remain useful as migration history and contract background, but they should no longer be treated as the authoritative final-state architecture.
