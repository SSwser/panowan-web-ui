# Canonical Task UI, Cancellation, and Worker Visibility Design

> This design follows ADR 0010 and the existing canonical lifecycle work already present on this branch. It defines the immediate product and implementation shape for aligning the browser UI, cancellation semantics, and worker observability with the canonical task model.

## 1. Goal

Align the end-to-end task experience on one canonical lifecycle so that:

- task status updates appear live in the browser without manual refresh,
- terminal task states render the correct translated labels and actions,
- cancellation behaves as cooperative soft cancellation with explicit UI feedback,
- and operators can see the current worker and queue state both in the UI and backend logs.

## 2. Scope

This design covers:

- browser rendering of canonical task states,
- browser action availability per canonical state,
- cooperative cancellation semantics for queued and in-flight jobs,
- worker summary visibility above the task list,
- backend task-state transition logging,
- backend periodic queue/worker summary logging,
- and the API surface needed to support the worker summary UI.

## 3. Non-Goals

This design does not:

- introduce backward-compatibility shims for pre-canonical UI state values,
- preserve obsolete display-only states such as `completed` when the canonical state is `succeeded`,
- add a new persistent canonical state for `cancel_failed`,
- or redesign the entire persistence model beyond what is needed for this end-to-end alignment.

## 4. Product Decisions

### 4.1 Single source of truth

The backend canonical task `status` field is the only lifecycle truth.

The frontend may translate canonical states into user-facing labels, but it must not invent or persist a separate lifecycle vocabulary. In particular, the browser must stop assuming legacy states such as `completed` and instead render directly from canonical states.

### 4.2 Canonical task states to support end-to-end

The browser and API contract for this flow must support the current canonical states:

- `queued`
- `claimed`
- `running`
- `cancelling`
- `succeeded`
- `failed`
- `cancelled`

No compatibility alias layer will be added for older UI-only states.

### 4.3 Soft cancellation semantics

Cancellation is cooperative.

- `queued` + cancel request -> `cancelled`
- `claimed` + cancel request -> `cancelling`
- `running` + cancel request -> `cancelling`
- `cancelling` + worker honors stop -> `cancelled`

The worker owns the final `cancelled` write for in-flight work once execution has actually stopped.

### 4.4 No persistent `cancel_failed` state

A failed cancellation is treated as an operation result, not a lifecycle state.

If a user requests cancellation but the job still completes normally before the worker can stop it, the canonical terminal state remains `succeeded`.

The UI may show an ephemeral notice such as "取消未生效，任务已完成", but canonical persisted state must remain `succeeded`.

## 5. Frontend Design

### 5.1 Status rendering

The browser must render badges directly from canonical states.

| Canonical state | Label | Notes |
|---|---|---|
| `queued` | 排队中 | Waiting for a worker slot |
| `claimed` | 排队中 | Claimed but not yet actively generating; still not user-visible progress |
| `running` | 生成中 | Active execution |
| `cancelling` | 正在取消 | Cancellation requested and not yet finalized |
| `succeeded` | 已完成 | Terminal success state |
| `failed` | 失败 | Terminal failure state |
| `cancelled` | 已取消 | Terminal cancelled state |

`claimed` intentionally renders the same user-facing label as `queued` because it is an internal scheduling state, not a meaningful product distinction.

### 5.2 Action availability

The task action column must be keyed off canonical states:

- `queued`: show `取消`
- `claimed`: show `取消`
- `running`: show `取消`
- `cancelling`: show disabled or non-clickable `正在取消…`
- `succeeded`: show preview / download / upscale actions
- `failed`: show error details only
- `cancelled`: no further task actions

This is necessary so that completed jobs immediately expose preview, download, and upscale actions as soon as the SSE stream publishes `succeeded`.

### 5.3 Live updates

The browser will continue to use the existing SSE stream for incremental updates.

However, the render path must stop filtering behavior through the old four-state UI model. Receiving `succeeded`, `cancelled`, `cancelling`, or `claimed` from SSE must immediately update the visible row without requiring a manual page refresh.

### 5.4 Cancellation feedback in the UI

The browser must provide explicit cancellation feedback:

- immediately after a successful cancel request for queued work: row changes to `已取消`,
- immediately after a successful cancel request for in-flight work: row changes to `正在取消`,
- when the worker finalizes cancellation: row changes to `已取消`,
- if completion wins the race after a cancel request: row changes to `已完成` and the browser shows a one-time notice that cancellation did not take effect in time.

The UI must not silently leave the row looking unchanged after the user clicks cancel.

### 5.5 Worker summary above the task list

A new summary section will appear above the task-history table.

It must show at least:

- total workers,
- online workers,
- busy workers,
- queued jobs,
- running jobs.

If available from the backend summary payload, it should also show:

- total concurrent capacity,
- occupied capacity,
- panowan runtime readiness summary.

This section is intended to answer operational questions such as:

- why is a job still queued,
- whether any workers are online,
- whether cancellation is waiting on a currently busy worker,
- and whether the fleet is saturated.

## 6. Backend Design

### 6.1 API returns canonical states only

The API and SSE payloads must expose canonical state values only.

No endpoint in this flow should rewrite `succeeded` into `completed` or introduce any UI-only aliases.

### 6.2 Worker summary endpoint

Add a dedicated API response for the worker summary UI.

The payload should include aggregate counts derived from the worker registry and job backend, such as:

- `total_workers`
- `online_workers`
- `busy_workers`
- `queued_jobs`
- `running_jobs`
- `total_capacity`
- `occupied_capacity`
- `panowan_runtime_ready_workers` or equivalent readiness counts

The exact field names may vary, but the response must be designed as a summary contract rather than forcing the browser to reconstruct the operational picture from unrelated raw records.

### 6.3 Cooperative cancellation for Panowan jobs

`PanoWanEngine` must consume the worker cancellation callback so that in-flight generation can stop cooperatively.

The implementation must ensure that:

- the engine can observe cancellation during execution,
- the worker can finalize `cancelling -> cancelled` only after execution has actually stopped,
- and a late completion cannot overwrite an already terminal cancelled record.

If the underlying runtime only supports coarse cancellation checkpoints, that is acceptable for the first pass, but the control flow must still be wired end-to-end.

### 6.4 Transition event logs

Every meaningful task transition should emit a structured log line containing at least:

- `job_id`
- `from_status`
- `to_status`
- `job_type`
- `worker_id` when present
- reason or source, such as `api_cancel_request`, `worker_started`, `worker_completed`, `worker_failed`, `worker_cancelled`

The point of these logs is to make lifecycle behavior inspectable without diffing raw JSON stores by hand.

### 6.5 Periodic summary logs

The backend should emit a periodic operational summary at a fixed interval.

The summary should include at least:

- queued count,
- claimed count,
- running count,
- cancelling count,
- succeeded count,
- failed count,
- cancelled count,
- online worker count,
- busy worker count,
- identifiers of active jobs when practical.

These logs are for debugging live queue behavior and verifying whether the system is progressing or stuck.

## 7. Canonical Race Rules

### 7.1 Cancel vs completion

If a cancel request arrives while a job is in flight, the canonical outcome is determined by the actual lifecycle transition order:

- if the worker stops execution and finalizes cancellation first, terminal state is `cancelled`,
- if execution completes successfully before cancellation is actually honored, terminal state is `succeeded`.

This race must be resolved by lifecycle rules, not by whichever caller writes last.

### 7.2 Cancel vs failure

If a job fails before cooperative cancellation completes, terminal state is `failed`.

The browser may still reflect that a cancellation had been requested, but the persisted lifecycle state remains the true terminal execution outcome.

### 7.3 Terminal immutability

Once a job reaches `succeeded`, `failed`, or `cancelled`, no subsequent path may move it into another state.

## 8. Testing Requirements

### 8.1 Frontend tests

Add or update tests that prove:

- canonical states map to the intended badges,
- `succeeded` immediately reveals preview / download / upscale actions,
- `cancelling` shows non-clickable cancellation-in-progress UI,
- `cancelled` shows translated terminal UI,
- SSE-delivered canonical states update visible rows without a full reload.

### 8.2 API and lifecycle tests

Add or update tests that prove:

- queued cancellation transitions directly to `cancelled`,
- claimed/running cancellation transitions to `cancelling`,
- final cooperative stop transitions `cancelling -> cancelled`,
- terminal states cannot be overwritten,
- cancel/complete races resolve deterministically.

### 8.3 Worker/runtime tests

Add or update tests that prove:

- Panowan execution observes the cancellation callback,
- cancellation can stop in-flight work cooperatively,
- late completion does not overwrite an already cancelled job,
- periodic summary logging and transition logging are emitted in the expected situations.

## 9. Implementation Sequence

1. Remove the old browser assumptions that only four task states exist.
2. Update browser badge rendering and action rendering to consume canonical states directly.
3. Add explicit browser UX for `cancelling` and `cancelled`.
4. Add the worker summary API contract.
5. Add the worker summary section above the task list.
6. Wire Panowan execution to consume cooperative cancellation signals.
7. Add transition event logs and periodic operational summary logs.
8. Lock the new behavior with frontend, API, lifecycle, and worker tests.

## 10. Acceptance Criteria

This work is complete when all of the following are true:

- a task row updates live in the browser when its canonical state changes,
- a successful job that reaches `succeeded` immediately exposes preview, download, and upscale actions,
- cancellation of queued work moves directly to `cancelled`,
- cancellation of in-flight work visibly enters `cancelling` and eventually resolves to either `cancelled`, `failed`, or `succeeded` according to actual execution outcome,
- the browser never displays raw untranslated lifecycle values like `success` or `cancel`,
- the task list shows a worker summary above the table,
- and backend logs make current queue and worker state inspectable in real time.
