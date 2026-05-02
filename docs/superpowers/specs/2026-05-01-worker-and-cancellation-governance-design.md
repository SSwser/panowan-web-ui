# Worker and Cancellation Governance Design

> This design is a focused follow-up to the canonical task UI and cancellation work. It keeps ADR 0010 as the lifecycle source of truth, but narrows this iteration to the places where the current implementation still diverges from runtime reality: worker-summary correctness, bounded cancellation convergence, and backend-agnostic cancellation capability.

## 1. Goal

Align cancellation, worker occupancy, and worker observability on one shared governance model so that:

- `cancelling` can never remain stuck indefinitely,
- in-flight cancellation converges to a real terminal outcome owned by the worker/runtime layer,
- worker summary counts remain trustworthy even when a runtime is slow to stop or a worker becomes unhealthy,
- and cancellation becomes a common runtime capability instead of a PanoWan-specific wiring path.

## 2. Scope

This design covers:

- the shared cancellation capability contract between worker and runtime,
- timeout-based adjudication for stuck `cancelling` jobs,
- worker-owned finalization of in-flight cancellation outcomes,
- worker summary contract changes needed to avoid misleading total/online/busy counts,
- retry and escalation UX for long-lived `cancelling` jobs,
- and resilience rules for worker disconnects, stale heartbeats, and lost progress messages.

## 3. Non-Goals

This design does not:

- introduce a new persistent canonical terminal state such as `cancel_timeout` or `cancel_failed`,
- redesign the entire worker registry architecture into a full distributed lease service,
- add hard OS-level process termination as the default cancellation behavior,
- or preserve legacy API/UI cancellation naming that conflicts with the canonical lifecycle model.

## 4. Problem Statement

The current branch fixed the first-pass product gap: canonical task states render in the UI, cancellation visibly enters `cancelling`, and the worker summary is exposed above the task list.

However, three correctness gaps remain:

1. `total_workers` can drop to `0`, which makes the worker overview untrustworthy.
2. `cancelling` has no bounded convergence rule, so a job can remain stuck indefinitely.
3. cancellation is still wired like a backend-specific path rather than a shared runtime capability.

These are not separate bugs. They are symptoms of one architectural gap: the system still lacks a single authority that owns the relationship between cancel intent, runtime stop behavior, worker slot release, and worker summary reporting.

## 5. Product Decisions

### 5.1 API requests cancellation; worker/runtime adjudicates it

The API remains responsible for recording user intent:

- `queued` + cancel request -> `cancelled`
- `claimed` + cancel request -> `cancelling`
- `running` + cancel request -> `cancelling`

But for in-flight work, the API is not allowed to decide the terminal outcome.

The worker/runtime layer is the only authority that may converge `cancelling` into a final state after active execution has actually stopped or definitively failed to stop.

### 5.2 `cancelling` must always have a deadline

Every in-flight cancellation must carry a bounded timeout window.

Required metadata:

- `cancel_requested_at`
- `cancel_deadline_at`
- `cancel_mode` (`soft` or `escalated`)
- `cancel_attempt` (monotonic count)

If the runtime has not stopped execution by `cancel_deadline_at`, the worker/runtime layer must adjudicate the task to canonical terminal state `failed`.

No job may remain in `cancelling` without an active deadline.

### 5.3 Timeout outcome is `failed`, not a new terminal state

If cancellation does not converge in time, terminal outcome becomes `failed`.

The system must not introduce a new canonical state such as `cancel_failed` or `cancel_timeout`. Those are operation/result details, not lifecycle categories.

Failure reason metadata may distinguish:

- `cancel_timeout`
- `worker_lost_during_cancellation`
- `runtime_rejected_cancellation`
- `forced_cancel_failed`

But persisted lifecycle state remains canonical `failed`.

### 5.4 Worker truth and task truth must converge together

A timed-out cancellation cannot be implemented as a task-only rewrite.

If a worker/runtime owns an in-flight job, only that worker/runtime path may:

- finalize `cancelling -> cancelled`,
- finalize `cancelling -> failed`,
- release the occupied slot,
- clear the running job from the worker registry view,
- and emit the corresponding transition/summary logs.

This avoids split-brain outcomes where the task appears terminal while the worker still looks busy or the runtime still holds GPU memory.

### 5.5 Cancellation is a common runtime capability

Cancellation must become a first-class runtime capability, parallel to resident runtime loading and runtime identity handling.

The system must stop treating `should_cancel` as a best-effort callback only used by one provider path.

Instead, runtime integration must expose a common capability contract such as:

- `supports_soft_cancel`
- `supports_escalated_cancel`
- `default_cancel_timeout_sec`
- `cancel_poll_interval_sec`
- `cancel_checkpoint_granularity`

Exact field names may differ, but the capability must be platform-owned and backend-agnostic.

### 5.6 Escalation is explicit, not implicit

When a job remains in `cancelling` long enough to worry the user, the UI may expose two second-stage actions:

- `重试取消`
- `确认强制取消`

These actions do not directly write terminal state.

They only update cancellation intent and mode so that worker/runtime executes a stronger cancellation policy. Final state still comes from actual execution outcome.

## 6. Worker Summary Design

### 6.1 Do not treat online count as total count

The worker summary must stop using one unstable observation bucket to answer multiple product questions.

The summary contract must separate at least these concepts:

- `configured_workers` or `known_workers`
- `online_workers`
- `busy_workers`
- `stuck_cancelling_workers`
- `queued_jobs`
- `running_jobs`
- `cancelling_jobs`
- `total_capacity`
- `occupied_capacity`
- `effective_available_capacity`

`configured_workers` / `known_workers` answers “how many workers exist in this fleet view”.

`online_workers` answers “how many currently have fresh heartbeat/registry presence”.

`busy_workers` answers “how many are actively holding execution slots”.

`stuck_cancelling_workers` answers “how many are still occupied by jobs whose cancellation has not yet converged”.

This split is required so the UI never implies “there are zero workers” when the actual truth is “workers exist, but none are currently healthy/available”.

### 6.2 Worker summary must surface unhealthy cancellation occupancy

The summary payload should surface whether capacity loss is caused by cancellation drag.

At minimum, the backend summary must make it possible for the browser and logs to distinguish:

- no workers configured,
- workers configured but all offline,
- workers online but all busy,
- workers online but one or more are stuck in cancellation convergence.

### 6.3 Cancellation drag is an operational signal, not just a task detail

A worker occupied by a long-lived `cancelling` job is not merely a job-row issue. It directly affects fleet throughput.

Therefore the summary and periodic logs must make cancellation drag visible as an operational condition.

## 7. Runtime Capability Design

### 7.1 Shared cancellation contract

Worker/runtime integration must promote cancellation into a common contract, not raw callback plumbing.

Illustrative shape:

- worker asks runtime capability whether soft cancellation is supported,
- worker enters `cancelling` and starts the cancellation deadline clock,
- runtime is polled or invoked at documented checkpoints,
- runtime reports one of: still_running / stopping / stopped / cannot_stop,
- worker uses that signal plus deadline to adjudicate final lifecycle outcome.

This contract belongs at the shared runtime host/provider boundary, not inside one engine implementation.

### 7.2 Soft cancel remains the default

The first cancellation request uses cooperative cancellation.

That means the runtime is given a chance to stop safely at checkpoints and release resources cleanly.

### 7.3 Escalated cancel is a stronger policy, not a separate lifecycle

If the user retries or explicitly confirms stronger cancellation, the cancellation mode becomes `escalated`.

Escalation may allow provider-specific stronger stop behavior if available, but it still feeds back into the same canonical lifecycle:

- stopped in time -> `cancelled`
- did not stop in time -> `failed`
- execution finished first -> `succeeded`
- execution failed first -> `failed`

### 7.4 Unsupported cancellation must be explicit

If a runtime cannot observe or honor cancellation at all, that must be expressed through capability metadata.

The worker may still accept the cancel request and move to `cancelling`, but the timeout window and expected failure path become explicit rather than pretending the backend supports a stop it cannot actually perform.

## 8. Canonical Race Rules

### 8.1 Cancel vs completion

If execution completes successfully before the runtime actually stops, terminal state is `succeeded`.

A cancellation request does not retroactively override successful completion.

### 8.2 Cancel vs timeout

If the deadline expires before runtime stop is confirmed, terminal state is `failed` with cancellation-timeout reason metadata.

### 8.3 Cancel vs worker loss

If the worker disappears during `cancelling` and the system cannot prove the runtime stopped cleanly, the task must converge to `failed`, not remain in `cancelling` forever.

### 8.4 Terminal immutability remains absolute

Once the task reaches `succeeded`, `failed`, or `cancelled`, no later API retry, stale worker report, or delayed runtime callback may move it into another lifecycle state.

## 9. Resilience Rules

### 9.1 Lost SSE or browser connection must not affect convergence

Browser connectivity is not part of cancellation correctness.

If the browser disconnects, the job must still converge server-side according to worker/runtime truth.

### 9.2 Worker heartbeat loss must trigger bounded adjudication

If a worker stops refreshing its registry/heartbeat while holding a `cancelling` job, the system must treat that as a bounded recovery path, not an indefinite wait.

A reconciliation flow may wait for a short grace interval, but must then converge the task to `failed` if stop confirmation cannot be proven.

### 9.3 Periodic reconciliation must repair stuck `cancelling`

Independent of the live worker loop, a backend reconciliation path must periodically scan for:

- `cancelling` jobs past `cancel_deadline_at`,
- workers whose running-job registry entry conflicts with terminal task state,
- workers whose registry view has gone stale while holding in-flight jobs.

The reconciler does not invent success. It only drives unresolved situations toward safe failure when worker truth can no longer be established.

## 10. UI and API Contract Changes

### 10.1 Rename cancellation semantics away from legacy `force`

The public API and UI wording must stop implying that the first cancel request is a hard kill.

The first action is a cooperative cancel request.

Escalation, if exposed, should be modeled as a second explicit action rather than overloading the first request with legacy `force` naming.

### 10.2 `cancelling` rows need visible progress and recovery actions

A task row in `cancelling` should show:

- current cancellation label,
- whether the request is `soft` or `escalated`,
- whether it has timed out or is nearing timeout,
- and optional follow-up actions such as `重试取消` or `确认强制取消`.

The UI must not imply that no progress is happening when the system is actively attempting stop convergence.

### 10.3 One-time notices remain ephemeral

If cancellation loses the race to success, or times out into failure, the browser may show one-time explanatory notices.

These notices are display feedback only. They do not add new lifecycle states.

## 11. Logging and Observability

### 11.1 Transition logs must include cancellation governance fields

For cancellation-related transitions, logs should include at least:

- `job_id`
- `from_status`
- `to_status`
- `worker_id`
- `cancel_mode`
- `cancel_attempt`
- `cancel_requested_at`
- `cancel_deadline_at`
- `reason`

### 11.2 Periodic summary logs must expose cancellation drag

Periodic operational summaries should include at least:

- `online_workers`
- `busy_workers`
- `stuck_cancelling_workers`
- `queued_jobs`
- `running_jobs`
- `cancelling_jobs`
- active job identifiers when practical

This is required so operators can tell the difference between a normal busy fleet and a fleet degraded by stuck cancellation.

## 12. Testing Requirements

### 12.1 Lifecycle tests

Add or update tests that prove:

- `running -> cancelling` always attaches a deadline,
- past-deadline `cancelling` converges to `failed`,
- timeout metadata does not create a new canonical state,
- terminal states remain immutable after timeout adjudication.

### 12.2 Worker/runtime tests

Add or update tests that prove:

- the runtime capability contract is shared and not PanoWan-specific,
- a cancellation-aware runtime can stop cooperatively and produce `cancelled`,
- a non-responsive runtime causes `cancelling -> failed` at deadline,
- worker slot release and registry cleanup occur with terminal adjudication,
- stale worker heartbeats during `cancelling` converge safely.

### 12.3 API tests

Add or update tests that prove:

- API cancel requests create `cancel_requested_at` / `cancel_deadline_at` metadata for in-flight jobs,
- API does not directly finalize in-flight `cancelling` jobs,
- escalation actions change cancellation intent/mode but do not bypass worker-owned finalization.

### 12.4 Worker summary tests

Add or update tests that prove:

- `configured_workers` / `known_workers` cannot collapse to `0` merely because all workers are offline,
- `busy_workers` and `stuck_cancelling_workers` are reported distinctly,
- effective available capacity reflects cancellation drag correctly.

### 12.5 UI tests

Add or update tests that prove:

- `cancelling` shows timeout-aware feedback,
- retry/escalation actions are available only in the intended states,
- worker summary distinguishes total/online/busy/stuck conditions,
- timeout or recovery outcomes update live without refresh.

## 13. Implementation Sequence

1. Introduce shared cancellation capability metadata at the worker/runtime boundary.
2. Teach the worker lifecycle to own cancellation deadlines and terminal adjudication.
3. Add reconciliation for overdue `cancelling` jobs and stale worker occupancy.
4. Replace the legacy worker-summary aggregation with separated total/online/busy/stuck counts.
5. Rename public API/UI cancellation semantics away from legacy `force` wording.
6. Add second-stage retry/escalation actions in the browser.
7. Lock the behavior with lifecycle, worker, API, summary, and UI tests.

## 14. Acceptance Criteria

This work is complete when all of the following are true:

- no in-flight cancellation can remain in `cancelling` forever,
- cancellation timeout converges to canonical `failed` with consistent worker slot release,
- worker summary never misrepresents “all workers unavailable” as “zero workers exist”,
- operators can tell from logs and summary whether capacity is blocked by cancellation drag,
- cancellation support is modeled as a shared runtime capability rather than a PanoWan-specific special case,
- and the UI provides bounded, understandable feedback for retry/escalation without inventing new lifecycle states.

## 15. Related Documents

- [ADR 0010: Canonical Task State and Transition Governance](../../adr/0010-canonical-task-state-and-transition-governance.md)
- [ADR 0004: Worker Registry and Communication Boundary](../../adr/0004-worker-registry-and-communication-boundary.md)
- [ADR 0009: Worker-Owned Resident Runtime Host](../../adr/0009-worker-owned-resident-runtime-host.md)
- [Canonical Task UI, Cancellation, and Worker Visibility Design](2026-05-01-canonical-task-ui-and-cancellation-design.md)
- [Task State Governance Follow-up Spec](2026-05-01-task-state-governance-followups.md)
