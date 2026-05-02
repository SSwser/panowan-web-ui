# 2026-05-02 Resident Runtime Cancellation Refactor Design

## Summary

Refactor the task execution and cancellation architecture so that:

1. job lifecycle reflects real execution boundaries rather than worker ownership timing
2. runtime/model loading is separated from job execution semantics
3. cancellation is modeled as an execution-layer capability, not only an API/storage-layer state change
4. the architecture is prepared for future step-level interrupt support without requiring another state-machine rewrite
5. resident model reuse / VRAM reuse remains the primary optimization target

This is a forward-only refactor. Backward compatibility shims are intentionally out of scope.

---

## Problem Statement

The current implementation mixes together three different concerns:

1. **job lifecycle**
   - whether a business task is queued, executing, cancelling, or finished

2. **worker/runtime lifecycle**
   - whether a worker/runtime is cold, loading, warm, or actively executing

3. **execution interrupt capability**
   - whether the underlying provider can stop a currently running inference invocation

This coupling causes incorrect behavior and misleading semantics:

- jobs enter `running` too early, immediately after worker claim
- model loading time is incorrectly represented as generation time
- cancellation during runtime preparation is treated too similarly to cancellation during active generation
- `cancelling` becomes a catch-all waiting state instead of a precise execution-phase state
- API cancellation may succeed semantically while the underlying inference call continues to run for a long time
- the system has no clean way to represent different interrupt strengths across providers

The result is a design that is operationally confusing, difficult to extend, and unable to support stronger generation-time cancellation cleanly.

---

## Goals

### Primary goals

1. Separate runtime/worker busy state from job business lifecycle.
2. Ensure a job enters `running` only when real task execution begins.
3. Treat runtime loading as worker activity, not as job generation.
4. Make load-phase cancellation distinct from execute-phase cancellation.
5. Redefine `cancelling` to mean only “an executing job is converging toward cancellation”.
6. Preserve resident model reuse and VRAM reuse as the default behavior.
7. Introduce contracts that allow future step-level interrupt support without another architecture rewrite.

### Secondary goals

1. Make provider interrupt capability explicit and queryable.
2. Make escalation meaningful at the execution layer, not just as metadata.
3. Improve observability so UI and logs can explain what the system is actually waiting for.

---

## Non-Goals

1. Implementing guaranteed step-level interrupt for the current PanoWan provider in this phase.
2. Preserving legacy state semantics or legacy API assumptions.
3. Designing a generic distributed scheduler.
4. Supporting providers that need no resident runtime model.
5. Introducing kill-process cancellation as the primary path.

---

## Design Principles

1. **State truth must follow physical execution boundaries**
   - if a task has not entered real inference execution, it is not `running`

2. **Worker/runtime lifecycle and job lifecycle are different state machines**
   - they may correlate, but one must not be encoded by overloading the other

3. **Cancellation is a capability, not a boolean**
   - different providers can support different interrupt strengths

4. **Resident runtime reuse is the default**
   - any stronger cancel path must justify how it preserves or intentionally sacrifices reuse

5. **No transitional compatibility layer**
   - refactor directly to the target architecture

---

## Canonical State Model

### Job states

Job states remain:

- `queued`
- `claimed`
- `running`
- `cancelling`
- `succeeded`
- `failed`
- `cancelled`

### Revised meanings

#### `queued`
The job exists in the backend and has not yet been accepted by a worker for execution preparation.

#### `claimed`
The job has been accepted by a worker and is associated with a worker/runtime preparation path, but has **not** entered actual inference execution.

This includes:
- waiting for runtime selection
- waiting for runtime readiness
- waiting for model loading
- waiting for resource handoff before execution begins

#### `running`
The job has entered actual provider execution. This is the beginning of real generation/inference work.

#### `cancelling`
The job was already `running`, a cancellation request was accepted, and the execution layer is converging toward cancellation.

This state is only valid for execute-phase cancellation.

#### `cancelled`
The job was cancelled before completion and the execution layer converged successfully.

#### `failed`
The job failed due to execution failure or cancellation timeout/failure to converge.

#### `succeeded`
The job completed normally.

---

## Runtime State Model

Runtime state is independent from job state.

### Runtime states

- `cold`
- `loading`
- `warm`
- `running`
- `evicting`
- `failed`

### Meanings

#### `cold`
No loaded runtime is available.

#### `loading`
The runtime is being prepared or loaded. The worker is busy, but the claimed job has not yet entered generation.

#### `warm`
A loaded runtime exists and is ready for reuse.

#### `running`
The runtime is actively executing a job.

#### `evicting`
The runtime is being torn down or replaced.

#### `failed`
The runtime is not trustworthy and must not be reused until reset/teardown.

---

## Required Separation Between Job and Runtime State

The system must support these truths simultaneously:

- a worker can be busy while no job is `running`
- a runtime can be `loading` while a job remains `claimed`
- a job can be `claimed` even though the worker is not yet executing inference
- a runtime can return to `warm` after a job finishes or is cancelled
- cancellation semantics depend on whether the job is still `claimed` or already `running`

This separation is the core architectural correction in this refactor.

---

## Canonical Job Transitions

### Allowed transitions

- `queued -> claimed`
- `queued -> cancelled`
- `claimed -> running`
- `claimed -> cancelled`
- `claimed -> failed`
- `running -> succeeded`
- `running -> failed`
- `running -> cancelling`
- `cancelling -> cancelled`
- `cancelling -> failed`

### Explicitly disallowed as normal-path semantics

- `claimed -> cancelling`
- `queued -> running`
- `queued -> failed` except via explicit adjudication/reconciliation
- any runtime state embedded into job state

`claimed -> cancelling` is intentionally removed as a normal operational path because load/preparation cancellation is not execute-phase cancellation.

---

## Cancellation Semantics

Cancellation behavior depends on the current job phase.

### Queue-phase cancellation

#### `queued`
Cancellation immediately transitions the job to `cancelled`.

No worker-side convergence is required.

---

### Prepare-phase cancellation

#### `claimed`
Cancellation immediately transitions the job to `cancelled`.

If a runtime load or prepare operation is already underway, the runtime layer may observe the cancellation request and abandon preparation as early as possible, but the job does not enter `cancelling`.

This is not treated as generation-time cancellation.

---

### Execute-phase cancellation

#### `running`
Cancellation transitions the job to `cancelling`.

The runtime/provider execution path must receive a cancellation object that expresses:
- cancellation requested
- interrupt mode
- escalation level
- deadline
- attempt count

The job remains `cancelling` only while waiting for execution-layer convergence.

Possible terminal outcomes:
- `cancelled`
- `failed` with `cancel_timeout`
- `failed` with execution error if cancellation causes or exposes a failure condition

---

## Escalation Semantics

Escalation is not a second copy of cancel. It is a stronger execution-layer interrupt request.

### Interrupt modes

At minimum, the design supports these conceptual modes:

- `soft`
- `escalated`

Future providers may expose finer levels, but the architecture only requires these two in this phase.

### Soft cancellation

Intended behavior:
- allow safe checkpoint-based interruption
- preserve runtime reuse whenever possible
- avoid aggressive teardown

### Escalated cancellation

Intended behavior:
- request the strongest non-destructive interrupt supported by the provider
- increase checkpoint aggressiveness if supported
- abandon optional post-processing if supported
- prepare runtime reset if cancellation cannot converge safely

Escalation does **not** imply process kill. It means “use the strongest available task-level interruption path that still respects the provider contract”.

---

## Timeout and Terminal Adjudication

### Cancellation deadline

When a `running` job enters `cancelling`, the system records:

- `cancel_requested_at`
- `cancel_deadline_at`
- `cancel_mode`
- `cancel_attempt`

If convergence is not achieved before the deadline:

- the job transitions to `failed`
- `error = "cancel_timeout"`
- `error_code = "cancel_timeout"`

### Runtime consequence after timeout

After `cancel_timeout`, the runtime host must decide whether the runtime remains trustworthy.

This is not encoded in job state. It is a runtime decision based on provider capability and observed failure mode.

Possible outcomes:
- runtime returns to `warm`
- runtime enters `failed`
- runtime is evicted/reset before reuse

---

## Restart and Recovery Semantics

### Restored in-flight records

On restore, any non-terminal job must be reconciled to a terminal outcome according to canonical lifecycle rules.

### Restored `cancelling`

Any restored `cancelling` job must become:

- `failed`
- `error = "cancel_timeout"`
- `error_code = "cancel_timeout"`

Reason:
after restart, the original execution context is gone, so the system must not pretend cancellation convergence can still continue.

### Restored `claimed` / `running` / `queued`

These remain restart-reconciliation failures unless a more specific restore contract is introduced later.

This preserves the existing principle that uncertain in-flight work must not be fabricated into success.

---

## Architecture Refactor

## 1. `app/worker_service.py`

### New responsibility

`worker_service` becomes the single orchestrator of **job lifecycle**.

It is responsible for:
- claiming jobs
- deciding when a job becomes `running`
- deciding whether cancellation is prepare-phase or execute-phase
- finalizing job outcomes based on provider/runtime results

### New execution structure

The worker flow becomes:

1. **claim phase**
   - `queued -> claimed`

2. **prepare phase**
   - request runtime readiness from runtime host
   - runtime may be `cold`, `loading`, `warm`, or require identity replacement
   - job remains `claimed`

3. **execute phase**
   - once runtime is ready, explicitly transition `claimed -> running`
   - execute job through runtime host
   - if cancel requested during execution, `running -> cancelling`

4. **finalization phase**
   - convert execution result into `succeeded`, `cancelled`, or `failed`

### Key rule

`worker_service` is the only layer allowed to move a job from `claimed` to `running`.

Runtime host and provider must not mutate job state.

---

## 2. `app/runtime_host.py`

### New responsibility

`runtime_host` manages **runtime lifecycle**, not job lifecycle.

### Required public shape

The host must be conceptually split into two phases:

#### `prepare_runtime(...)`
Responsibilities:
- determine runtime identity
- evict incompatible warm runtime if needed
- load runtime if cold
- return a ready runtime handle or raise

This phase may observe cancellation, but it does not imply job `running`.

#### `execute_job(...)`
Responsibilities:
- switch runtime to active execution
- invoke provider execution
- restore runtime to `warm` or `failed`
- return execution outcome

This phase corresponds to job `running`.

### Why this split matters

Without this split, the system cannot truthfully represent:
- loading without running
- claimed without generation
- prepare-phase cancel vs execute-phase cancel

---

## 3. Provider Contract

The provider contract must be refactored to reflect the final desired architecture, even if the current PanoWan provider initially implements only a subset strongly.

### Required provider concerns

#### Runtime identity
- `runtime_identity_from_job(job)`

#### Prepare/load
- `load(identity, cancellation, context)`

#### Execute
- `execute(loaded_runtime, job, cancellation, context)`

#### Teardown
- `teardown(loaded_runtime)`

#### Failure classification
- `classify_failure(exc)`

#### Interrupt capability declaration
The provider must explicitly describe what interrupt features it supports.

Examples of capability dimensions:
- load-phase cancel awareness
- execute soft interrupt
- execute step-level interrupt
- execute escalated interrupt
- destructive reset required after failed interrupt

### Why capability declaration is needed

The system must stop pretending every provider can interrupt equally. API, worker_service, and runtime_host need a truth source for what kind of cancellation semantics are physically possible.

---

## 4. Cancellation Object

The existing cancellation probe must evolve into a richer interrupt-strategy object.

### Required fields/behaviors

At minimum, the object must provide:

- whether cancellation has been requested
- current mode: soft vs escalated
- attempt count
- deadline
- helpers such as:
  - `should_stop_now()`
  - `should_escalate()`

### Purpose

This object is how execution-layer policy is carried downward without hard-coding policy into providers.

It allows:
- worker_service to declare intent
- runtime_host to pass it through unchanged
- providers to respond according to capability

---

## 5. `app/jobs/lifecycle.py`

This remains the sole legal source of job-state transitions.

It must be updated to encode the new strict semantics:
- `claimed` is pre-execution
- `cancelling` is execute-phase only
- load/runtime states do not leak into job state

This file must reject any future attempt to reintroduce mixed semantics.

---

## 6. `app/api.py`

### New responsibility

API becomes a thin governance layer.

It may:
- request cancellation
- request escalation
- return job state
- return worker/runtime summary

It must not:
- assume `claimed` means “actively generating”
- imply escalation guarantees a physical interrupt
- synthesize runtime semantics that the provider contract has not declared

---

## Data Model Changes

The job record should continue to store cancellation governance metadata for execute-phase cancellation:

- `cancel_requested_at`
- `cancel_deadline_at`
- `cancel_mode`
- `cancel_attempt`

However, these fields are meaningful only for execute-phase cancellation, not prepare-phase cancellation.

### Optional runtime-side state

Runtime-side interruption bookkeeping should stay in runtime/worker structures, not job state, unless it is required for observability.

Examples:
- current runtime state
- current runtime identity
- provider interrupt capability snapshot
- whether runtime reset is pending after timeout

---

## Result Model

Execution result handling should be normalized so that worker_service can finalize outcomes consistently.

### Desired result categories

Providers should converge on returning outcomes that can be normalized into:

- success
- cancelled
- failure

The worker_service must not infer too much from partial provider return shapes. A clear normalized result model reduces accidental lifecycle drift.

---

## Observability and UI Implications

This refactor should make UI and logs more truthful.

### UI implications

The UI can distinguish:
- job is claimed / waiting for runtime
- worker is loading
- job is running
- job is cancelling
- cancellation timed out

This is strictly better than treating all worker activity as generation.

### Logging implications

Logs should clearly differentiate:
- claimed
- runtime loading
- runtime warm
- running
- cancelling
- cancelled
- cancel timeout
- runtime reset after failed cancellation

The point is not more logging volume. The point is logging with correct semantics.

---

## Error Handling Rules

### Load failure
If runtime preparation fails before execution begins:
- job transitions from `claimed -> failed`
- no `cancelling` state is involved

### Execute failure
If execution fails without cancellation intent:
- `running -> failed`

### Cancel timeout
If execution cancellation does not converge before deadline:
- `cancelling -> failed(cancel_timeout)`

### Runtime corruption
If the provider classifies a failure as corrupting:
- runtime enters `failed`
- subsequent reuse is blocked until reset/teardown

---

## PanoWan-Specific First-Phase Expectations

The current vendored PanoWan provider only checks cancellation before and after the large `pipe(...)` call.

This refactor does **not** pretend that this is already strong execute-phase interruption.

### In this phase, PanoWan is expected to provide:

- correct load-vs-execute boundary participation
- correct prepare-phase vs execute-phase semantics
- cancellation object plumbing through runtime contracts
- truthful declaration of interrupt capability
- weak execute-phase cancellation if no deeper hook exists yet

### In a later phase, PanoWan may add:

- step-level callback integration
- interrupt flag propagation into the denoising loop
- stronger escalated cancellation handling while preserving runtime reuse

This is exactly why the architecture must be prepared now.

---

## Why This Is the Optimal Refactor

This design is preferred over a smaller patch because:

1. it corrects the state model at the real architectural boundary
2. it avoids encoding runtime details into job state
3. it removes the semantic lie that claim-time equals run-time
4. it supports resident runtime reuse as the default path
5. it makes future strong interrupt work an implementation extension instead of another state-machine rewrite

A smaller patch would leave the system structurally wrong and force another redesign later.

---

## Implementation Scope Boundary

This spec intentionally covers only the architectural refactor needed to:
- correct lifecycle semantics
- separate runtime preparation from execution
- prepare for stronger execution-layer interrupts

It does not require:
- immediate support for step-level interrupt in every provider
- new distributed control planes
- process-kill-based cancellation orchestration as a normal path

---

## Validation Strategy

The implementation derived from this spec must be validated with tests that prove:

1. `queued -> claimed` does not imply `running`
2. runtime `loading` can exist while job remains `claimed`
3. cancellation in `claimed` leads directly to `cancelled`
4. only execute-phase cancellation enters `cancelling`
5. `cancelling` converges to `cancelled` or `failed(cancel_timeout)`
6. restored `cancelling` records become `failed(cancel_timeout)`
7. runtime failure classification still governs reuse vs reset correctly
8. UI and API summaries no longer rely on the old overloaded semantics

---

## Open Follow-Up After This Spec

After this refactor lands, the next design question becomes narrower and cleaner:

- can the current PanoWan / underlying diffusion stack expose step-level interrupt checkpoints while preserving resident runtime reuse?

That should be treated as a provider capability enhancement, not as a lifecycle redesign.

---

## Final Recommendation

Proceed with a forward-only architectural refactor that:

1. keeps the existing canonical job state names
2. redefines `claimed`, `running`, and `cancelling` precisely
3. separates runtime preparation from job execution in the runtime host
4. makes worker_service the sole owner of job lifecycle orchestration
5. upgrades cancellation into a provider-aware interrupt contract
6. prepares for future strong execution interruption without requiring another redesign

This is the smallest refactor that is still structurally correct.
