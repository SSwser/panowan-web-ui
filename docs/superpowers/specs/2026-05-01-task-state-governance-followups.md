# Task State Governance Follow-up Spec

> This document follows ADR 0010. The ADR records the durable task lifecycle decisions. This spec captures the current review conclusions, implementation focus, and immediate corrective work needed to align the codebase with canonical state governance.

## 1. Goal and Scope

### Goal

Translate the newly formalized task-state architecture into concrete implementation work that reduces stale, delayed, or incorrect task status updates.

### Scope

This spec focuses on:

- introducing a centralized task state module,
- eliminating ad hoc state writes,
- defining the first implementation pass for cancellation / terminal-state / retry correctness,
- and using recent architecture review signals to prioritize where semantic drift is most likely.

### Non-Goals

This spec does not:

- redesign the entire task persistence model in one step,
- require a full event-sourcing migration,
- or couple task-state work to unrelated runtime feature expansion.

## 2. Why This Work Is Needed Now

The recent code review and runtime architecture work show a project that is becoming more explicit at execution boundaries:

- API and Worker runtime roles are more clearly separated,
- backend runtime requirements are more declarative,
- resident execution is moving toward platform-owned lifecycle management,
- and backend/root runtime integration contracts are becoming stricter.

That is good architectural progress.

However, the same trend raises the cost of ambiguous task-state semantics. As execution paths become more structured, any mismatch between runtime reality and task status becomes more visible and more damaging.

The user also reported repeated recent incidents where task state changes were delayed or displayed incorrectly. That makes this work corrective, not speculative.

## 3. Review Conclusions That Matter for Task-State Work

The current uncommitted runtime-focused diff was not primarily a task-lifecycle change set, but it revealed several architectural signals relevant to task-state governance.

### 3.1 Execution contracts are being tightened

Recent runtime changes strengthened:

- backend runtime dependency verification,
- backend materialization correctness,
- runtime provider contract clarity,
- and the split between API and Worker responsibilities.

This increases confidence in execution behavior, but it also means task-state semantics can no longer remain loosely inferred from whichever component happens to observe execution first.

### 3.2 Health/readiness semantics already show how easy display drift can happen

The `app/api.py` health behavior was changed so the split-topology API can report ready even though worker-only assets are not present locally.

That change may be correct for service readiness, but it is also a good warning sign: once a display-oriented status decouples from raw local asset visibility, the system needs very clear rules about what each surfaced status actually means.

Task state has the same risk on a larger scale.

Without a canonical lifecycle contract, one layer may surface “ready”, “running”, “done”, or “cancelled” based on local heuristics while another layer understands the underlying execution reality differently.

### 3.3 Consolidated runtime execution increases the importance of canonical outcome mapping

Recent runtime-provider and runner changes moved toward shared validation and execution semantics across CLI and resident execution paths.

That alignment is valuable because it reduces behavioral divergence.

The next equivalent step for task lifecycle is to ensure that all execution paths map outcomes back through one canonical state-transition module rather than letting each path write “success”, “error”, or “cancelled” directly.

### 3.4 Runtime verification now catches environment faults earlier

Backend verification now explicitly checks runtime commands and Python modules.

That means some failures that previously surfaced late during execution may now be detected earlier or more deterministically.

Task-state handling must therefore be explicit about how preflight failure, claim-time failure, runtime startup failure, and in-flight execution failure map into canonical lifecycle outcomes.

## 4. Target Implementation Shape

## 4.1 Introduce a dedicated task state module

Create one project-owned module responsible for:

- validating legal transitions,
- applying version/ownership checks,
- enforcing terminal-state immutability,
- attaching required metadata per transition,
- recording transition history or audit entries,
- and exposing helper operations for common lifecycle actions.

Illustrative operations:

- `create_task(...)`
- `claim_task(...)`
- `mark_running(...)`
- `request_cancellation(...)`
- `mark_succeeded(...)`
- `mark_failed(...)`
- `mark_cancelled(...)`
- `reconcile_stale_task(...)`
- `start_retry_attempt(...)`

The exact function names may differ, but the semantic entrypoints must be explicit.

## 4.2 Move all state mutation behind the module

The first implementation pass should identify every current place that writes task state directly and either:

- route it through the new module, or
- delete the duplicate write path.

This should include at least:

- API-originated task creation/cancellation intent,
- Worker claim/start/complete/fail flows,
- timeout or reconciliation flows,
- and any code that rewrites displayed state based on inferred local conditions.

## 4.3 Separate canonical state from display helpers

If the product needs friendlier UI labels or aggregate display states, derive them from canonical state plus metadata.

Do not expand the canonical task-state field just to satisfy display wording.

Examples:

- canonical `running` may render as “warming runtime” if progress metadata says a resident runtime is loading,
- canonical `failed` may render different failure badges based on error classification,
- canonical `cancelling` may render as “Stopping…” while the cooperative stop is in progress.

The display layer is allowed to interpret canonical state. It is not allowed to replace it.

## 4.4 Preserve terminal history across retries

The implementation must choose a concrete storage shape for attempts, but the first pass must already preserve the durable rule that retry does not erase prior terminal outcomes.

A minimal acceptable first version may:

- keep one logical task id,
- store an incrementing attempt counter,
- preserve terminal metadata for each attempt,
- and expose a current-attempt view to callers.

A more normalized lineage model can come later.

## 5. Immediate Correctness Rules to Enforce in Code

The first pass should explicitly lock the following rules in tests and implementation:

### Rule 1: No transition out of terminal states

Any attempt to move `succeeded`, `failed`, or `cancelled` back into a non-terminal state must fail loudly.

### Rule 2: Cancellation while running goes through `cancelling`

Do not jump directly from `running` to `cancelled` when active execution may still be producing side effects.

### Rule 3: Stale writers cannot overwrite newer state

Every mutation path must fail if its expected task version or ownership marker is stale.

### Rule 4: Completion and cancellation races resolve deterministically

If completion and cancellation signals arrive close together, the transition module must define one authoritative outcome based on actual observed ordering and allowed transitions, not on whichever caller happens to write last.

### Rule 5: Partial artifacts do not imply success

If runtime output exists but the system cannot prove successful completion, task state must not be set to `succeeded` purely because an artifact path exists.

### Rule 6: Failure classification influences metadata, not transition freedom

Failure classifiers may refine reason codes and recovery hints, but they do not gain authority to bypass canonical transition rules.

## 6. Recommended Work Sequence

### Step 1: State-write inventory

Locate every direct task-state write and classify it by source:

- API intent,
- Worker lifecycle,
- recovery/reconciler,
- UI projection,
- tests/fixtures.

Deliverable: one inventory list mapped to the future transition-module entrypoints.

### Step 2: Canonical transition table in code

Implement the transition graph and terminal-state guardrails in one pure, testable layer before refactoring storage callers.

Deliverable: pure transition tests covering allowed and rejected transitions.

### Step 3: Concurrency-aware persistence wrapper

Add version/ownership-aware persistence helpers around the transition layer.

Deliverable: tests proving stale writers cannot clobber newer state.

### Step 4: Route Worker lifecycle through the module

Worker claim/start/complete/fail/cancel flows should be the first real integration because they carry the most direct execution truth.

Deliverable: Worker no longer open-codes state transitions.

### Step 5: Route API cancellation and retry through the module

API code should request lifecycle actions, not write status values directly.

Deliverable: API intent maps into module calls with validated semantics.

### Step 6: Add reconciliation flows

Move timeout / abandoned-task recovery onto the same transition governance.

Deliverable: lease-expiry and stale-task tests.

## 7. Test Matrix

At minimum, add or update tests for the following scenarios:

### Core transition tests

- `queued -> claimed`
- `claimed -> running`
- `running -> succeeded`
- `running -> failed`
- `running -> cancelling -> cancelled`
- invalid transitions out of terminal states

### Cancellation race tests

- cancel requested before Worker starts execution
- cancel requested after claim but before actual run
- cancel requested during execution
- completion arrives after cancellation request
- failure arrives after cancellation request

### Concurrency tests

- stale version update rejected
- second Worker cannot claim already-claimed task without reconciliation
- late reconciler cannot overwrite newer terminal state

### Retry tests

- retry preserves prior terminal attempt
- retry creates a new active attempt
- retry from non-terminal state rejected unless explicitly allowed by future policy

### Recovery tests

- stale `claimed` task reconciled after lease expiry
- stale `running` task reconciled without falsely claiming success
- artifact exists but completion acknowledgement missing

### Display/read-model tests

- derived UI state comes from canonical state plus metadata
- display helper cannot mutate canonical state

## 8. Risks and Failure Modes

### Risk: hidden direct writes remain

Even after introducing a transition module, a few stray writes can preserve semantic drift.

Mitigation:

- inventory first,
- add grep-based checks or targeted code review gates,
- and prefer narrow persistence helpers over broad mutable model access.

### Risk: overloading canonical state with transient runtime phases

As runtime-host work grows, there will be pressure to encode warmup/loading/eviction directly as task states.

Mitigation:

- keep those signals in telemetry/progress metadata,
- preserve the canonical task state vocabulary from ADR 0010.

### Risk: reconciliation becomes too optimistic

Recovery code often “fills in the blanks” after crashes.

Mitigation:

- require positive evidence for success,
- bias unknown terminal situations toward explicit failure rather than fabricated success.

### Risk: migration introduces temporary UI mismatches

During rollout, some readers may still expect old status behavior.

Mitigation:

- define a temporary compatibility mapping in the read layer only,
- do not preserve old semantics by weakening the canonical transition rules.

## 9. Suggested Deliverables

1. A new centralized task state module.
2. A pure transition table and guardrail tests.
3. Version-aware persistence helpers.
4. Worker lifecycle integration onto the transition module.
5. API cancellation/retry integration onto the transition module.
6. Reconciliation integration and race-condition tests.
7. Removal of obsolete direct state writes.

## 10. Related Documents

- [ADR 0010: Canonical Task State and Transition Governance](../../adr/0010-canonical-task-state-and-transition-governance.md)
- [ADR 0004: Worker Registry and Communication Boundary](../../adr/0004-worker-registry-and-communication-boundary.md)
- [ADR 0009: Worker-Owned Resident Runtime Host](../../adr/0009-worker-owned-resident-runtime-host.md)
- [Platform Resident Runtime Host Design](2026-04-30-platform-resident-runtime-host-design.md)
