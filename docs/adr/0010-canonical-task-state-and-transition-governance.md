# ADR 0010: Canonical Task State and Transition Governance

Date: 2026-05-01
Status: Proposed

## Context

The project has repeatedly shown symptoms of task lifecycle semantics drifting across modules:

- state changes are sometimes delayed relative to execution reality,
- displayed status can diverge from backend execution state,
- terminal outcomes are not yet governed by one explicit contract,
- and new execution capabilities keep increasing the number of places that can mutate task state.

The runtime architecture is also becoming more explicit and more durable. Recent work strengthened backend runtime verification, split API and Worker runtime roles more clearly, and consolidated resident execution around shared runtime-provider contracts. That progress increases the cost of ambiguous task-state ownership, because execution behavior is becoming more structured while lifecycle semantics are still at risk of being inferred differently by API handlers, Worker logic, recovery flows, and UI readers.

This is no longer a one-off bug class. It is an architectural consistency problem.

The project needs one durable decision for:

- the canonical task state model,
- the legal transition rules,
- cancellation and retry semantics,
- terminal-state immutability,
- concurrency and recovery guarantees,
- and the ownership boundary for state mutation.

## Decision

Adopt a **canonical task state machine** governed by a **single project-owned transition module**.

### 1. Task state is a platform contract, not a handler-local detail

Task lifecycle semantics are a cross-cutting platform concern.

They must not be defined independently by:

- API request handlers,
- Worker execution loops,
- backend runtime adapters,
- recovery jobs,
- or UI formatting logic.

Those components may request a transition or react to a transition, but they do not define the meaning of task state.

### 2. One transition module owns all legal task-state mutation

The project must expose one canonical state-transition entrypoint.

That module owns:

- legal transitions,
- transition validation,
- transition-side metadata rules,
- terminal-state protection,
- version/concurrency checks,
- and normalization of user-visible lifecycle semantics.

Other modules must not open-code state mutation rules.

Direct writes that bypass transition policy are architectural violations, except for tightly-scoped persistence plumbing inside the state module itself.

### 3. Canonical task states are explicit and stable

The canonical task lifecycle states are:

- `queued`
- `claimed`
- `running`
- `cancelling`
- `succeeded`
- `failed`
- `cancelled`

These states are the durable product vocabulary.

If implementation internals require finer-grained substeps, those details belong in execution telemetry or progress metadata, not in the canonical state field.

### 4. Terminal states are immutable

The terminal task states are:

- `succeeded`
- `failed`
- `cancelled`

Once a task reaches a terminal state, its canonical state must not transition again.

Post-completion cleanup, artifact reconciliation, indexing, or telemetry backfill may append metadata, but must not rewrite the terminal state.

This rule exists because allowing terminal-state rewrites makes auditability and user trust collapse first at the exact point where the system most needs a stable outcome record.

### 5. Cancellation is two-phase when work may already be in flight

Cancellation is not modeled as an instantaneous rewrite from a non-terminal state to `cancelled` whenever execution may already be active.

Instead:

- `queued -> cancelled` is allowed when execution has not started,
- `claimed -> cancelling` is allowed when ownership exists and execution may start imminently,
- `running -> cancelling` is allowed when execution is active,
- `cancelling -> cancelled` is allowed when cooperative cancellation completes,
- `cancelling -> failed` is allowed only when the system cannot safely honor cancellation and execution terminates as an actual failure,
- `cancelling -> succeeded` is not allowed.

The intermediate `cancelling` state is required because user intent and actual runtime termination are not always simultaneous.

Typical flow:

- Task A is `running` on a Worker.
- User requests cancellation, so API records intent by moving Task A to `cancelling` rather than declaring it already finished.
- Worker observes `cancelling` at a safe checkpoint, stops further work, performs required cleanup, and only then moves Task A to `cancelled` or `failed` if cancellation could not complete cleanly.
- Only after Task A reaches a terminal state does the Worker claim the next queued task, allowing Task B to move from `queued` to `claimed` to `running` without overlapping the same execution slot.

This flow exists to keep cancellation truthful, keep terminal outcomes auditable, and prevent the next queued task from starting before the current one has actually released its execution slot.

### 6. Retry semantics create a new execution attempt

Retry must not silently reuse an already-terminal attempt as if its prior outcome never happened.

A retry is modeled as a new attempt under the same logical task lineage or under an explicitly linked successor task, depending on storage design.

Whichever storage shape the implementation uses, the durable rule is:

- terminal history remains preserved,
- a retry does not erase or rewrite the prior terminal outcome,
- user-visible “current attempt” views may collapse lineage for convenience,
- but the underlying execution history remains explicit.

### 7. State transitions require ownership and concurrency protection

A state mutation is valid only if the caller proves it is acting on the latest accepted task version and with the right ownership semantics.

The implementation may use version numbers, compare-and-swap updates, Worker lease ownership, or equivalent mechanisms. The durable requirement is architectural rather than storage-specific:

- concurrent writers must not be allowed to race silently,
- stale observers must not overwrite newer state,
- and recovery code must not “win” merely because it ran later.

### 8. Execution telemetry and canonical state are different layers

The project must distinguish between:

1. **canonical state** — durable user-facing lifecycle outcome,
2. **execution telemetry** — progress, substep, runtime status, percent complete, warm/cold runtime details, download phase, and other transient execution signals.

The canonical state model must remain small and stable.

This separation prevents the task state field from becoming an overloaded dump for every internal condition the runtime passes through.

### 9. API, Worker, reconciler, and UI have separate responsibilities

Responsibilities are divided as follows:

- **API** accepts user intent, creates tasks, and requests cancellation; it does not invent terminal outcomes.
- **Worker** owns task claim, execution start, execution completion, runtime-aware failure mapping, and cooperative cancellation observation.
- **Reconciler / recovery flows** detect abandoned ownership, timeouts, and stale in-flight tasks, and move them using the same canonical transition rules.
- **UI / read models** render canonical state and derived display helpers, but do not define semantics.

### 10. Failure classification may influence terminal outcome mapping, but not bypass governance

Backend/runtime code may classify execution failures to improve error reporting or recovery behavior.

However, backend-local code does not directly choose arbitrary task-state transitions.

Failure classification feeds the central transition module, which remains the only place that maps execution facts into canonical task-state changes.

## Canonical Transition Rules

The following transitions are allowed:

- `queued -> claimed`
- `queued -> cancelled`
- `claimed -> running`
- `claimed -> cancelling`
- `claimed -> failed`
- `running -> succeeded`
- `running -> failed`
- `running -> cancelling`
- `cancelling -> cancelled`
- `cancelling -> failed`

The following transitions are explicitly not allowed:

- any transition out of `succeeded`, `failed`, or `cancelled`
- `running -> queued`
- `running -> claimed`
- `cancelling -> running`
- `cancelling -> succeeded`
- `failed -> queued`
- `cancelled -> queued`
- `succeeded -> queued`

If future requirements introduce additional lifecycle states, they must be added by changing the canonical state model explicitly rather than by smuggling semantics into metadata.

## Required Metadata Semantics

A transition module must govern not only the target state, but also the minimum metadata that accompanies each transition.

Examples include:

- `queued`: creation metadata, request payload snapshot, initial attempt identity
- `claimed`: owner/lease metadata, claim timestamp
- `running`: execution-start timestamp, active attempt metadata
- `cancelling`: cancellation request source, requested-at timestamp
- `succeeded`: completed-at timestamp, stable output/artifact references, final execution summary
- `failed`: completed-at timestamp, failure classification/code, stable failure summary
- `cancelled`: completed-at timestamp, cancellation source and effective outcome summary

The exact field names may evolve, but the architectural rule is that state and its required metadata must be validated together. A transition is incomplete if it updates the state while leaving its minimum invariants ambiguous.

## Recovery and Reconciliation Guarantees

Recovery paths must use the same transition contract as normal execution.

This includes:

- reclaiming tasks abandoned by a dead Worker,
- converting stale `claimed` or `running` tasks after lease expiry,
- reconciling tasks whose runtime produced artifacts but crashed before final acknowledgement,
- and deduplicating late-arriving completion/failure signals.

Recovery logic must prefer correctness and explicitness over optimistic guesswork.

When the system cannot prove success, it must not manufacture `succeeded` from partial evidence. When it cannot prove that cancellation took effect, it must not claim `cancelled` prematurely.

## Observability and Audit

The system must preserve enough transition history to answer:

- who changed the task state,
- from which source of authority,
- at what time,
- from which prior version,
- and with what summarized reason or execution outcome.

The exact storage format may differ between event log, audit table, or embedded history, but the project must keep a reconstructable transition trail.

This is required both for debugging incorrect displays and for validating that reconciliation logic is behaving correctly under race conditions.

## Explicit Non-Decisions

This ADR does not yet decide:

1. the exact persistence schema for attempts or transition history,
2. whether retries are represented as child rows, attempt rows, or linked successor tasks,
3. the exact API response shape for display-specific derived statuses,
4. whether progress telemetry is stored inline or in a separate read model,
5. the exact timeout durations or lease-renewal intervals.

Those choices belong in implementation specs as long as they preserve the decisions in this ADR.

## Consequences

### Positive

- Creates one durable source of truth for task lifecycle semantics.
- Prevents terminal-state rewrites and silent race-induced regressions.
- Makes cancellation, retry, and recovery behavior explicit rather than inferred.
- Supports future execution-path growth without re-litigating core lifecycle rules in each module.
- Gives UI and API code a smaller, more stable contract.

### Negative

- Requires refactoring any existing direct state writes into the transition module.
- Forces some ambiguous current behaviors to become explicit and therefore testable.
- May require storage changes to support versioned updates, attempt lineage, or transition history.
- Makes some “quick fixes” slower because state mutation can no longer be patched ad hoc in arbitrary handlers.

## Alternatives Considered

1. **Leave state semantics distributed across API, Worker, and display logic** — rejected because recent incidents already show that distributed semantics drift under change.
2. **Document state rules only in an implementation spec** — rejected because the decision is cross-cutting and durable; it should outlive the current implementation pass.
3. **Model every internal substep as a canonical state** — rejected because it would make the state field unstable, noisy, and too coupled to backend/runtime internals.
4. **Allow terminal states to be corrected later by best-effort reconciliation** — rejected because it weakens auditability exactly where correctness matters most.

## Related Documents

- [ADR 0004: Worker Registry and Communication Boundary](0004-worker-registry-and-communication-boundary.md)
- [ADR 0006: Backend Runtime Input and Output Contract](0006-backend-runtime-input-and-output-contract.md)
- [ADR 0009: Worker-Owned Resident Runtime Host](0009-worker-owned-resident-runtime-host.md)
- [Task State Governance Follow-up Spec](../superpowers/specs/2026-05-01-task-state-governance-followups.md)
