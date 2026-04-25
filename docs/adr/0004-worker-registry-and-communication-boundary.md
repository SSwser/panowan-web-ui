# ADR 0004: Worker Registry and Communication Boundary

Date: 2026-04-25
Status: Proposed

## Context

ADR 0001 splits the product runtime into API, GPU Worker, and Model Setup roles. ADR 0003 defines backend runtime readiness as a worker-side concern: a registered backend is not necessarily available unless its files, weights, commands, and runtime dependencies validate in that worker environment.

The current local implementation uses `jobs.json` as a shared job queue between API and Worker. This is intentionally simple, but it creates an architectural boundary that must remain clear as the product moves toward persistent databases, distributed workers, concurrent execution, and richer scheduling.

The API needs enough information to decide whether a submitted request is schedulable. For example, an upscale request should not be accepted as runnable when no online worker can execute the requested upscale model. However, the API service must not inspect worker-local runtime paths such as `/engines/upscale`, `/opt/venvs/...`, or worker-mounted model assets. The API image is intentionally CPU-only and may not share the same filesystem or host as workers in future deployments.

## Decision

Define API/Worker communication around three explicit boundaries:

1. **Job Queue Boundary**
   - API creates jobs.
   - Workers claim jobs.
   - Job records are the durable API/Worker work contract.
   - The current adapter is `jobs.json` under `RUNTIME_DIR`.
   - A future adapter may be a database-backed queue, a message broker, or a scheduler-managed queue.

2. **Worker Registry Boundary**
   - Workers publish their runtime identity, health, capabilities, backend availability, and capacity state.
   - API and future schedulers read this registry for pre-submission schedulability checks.
   - The current adapter is `workers.json` under `RUNTIME_DIR`.
   - A future adapter may be database tables, a registry service, or a distributed control plane.

3. **Scheduling Boundary**
   - API may reject requests that have no currently schedulable worker.
   - API must not select work by inspecting worker-local runtime files.
   - Worker runtime validation remains authoritative at execution time.
   - Future schedulers may use worker registry state, leases, priorities, concurrency slots, and retry policy to assign or claim work.

This means Worker capability advertisement is a control-plane concern, while job execution remains a data-plane concern.

## Immediate Implementation

Use `${RUNTIME_DIR}/workers.json` as the first local Worker Registry adapter.

Each worker entry should include at least:

- `worker_id`
- `status`
- `capabilities`
- `available_upscale_models`
- `max_concurrent_jobs`
- `running_jobs`
- `last_seen`

Workers should write or refresh their registry entry after runtime validation and periodically during their polling loop. API should only treat entries as online if `last_seen` is within a configured stale timeout.

For the current upscale flow:

- API validates that the requested model name is known by product code.
- API checks Worker Registry for an online worker advertising the requested upscale model.
- Worker still validates its runtime before startup and before execution where applicable.
- If registry state is missing, stale, or does not contain a compatible worker, API returns an actionable client error rather than inspecting API-local runtime paths.

## Future Communication Protocol Direction

Future distributed communication should preserve these boundaries even if the adapters change.

A future implementation may replace JSON files with:

- persistent `jobs` storage,
- ephemeral `workers` or `worker_heartbeats` storage,
- worker capability records,
- scheduler-owned leases,
- queue visibility timeouts,
- cancellation propagation,
- retry and failure policies,
- and distributed concurrency slots.

The protocol should separate:

1. **Control plane** — worker heartbeat, capabilities, available backend models, health, capacity, runtime metadata.
2. **Data plane** — job payloads, outputs, status transitions, errors, cancellation state.
3. **Scheduling plane** — claim/lease semantics, priority, retries, concurrency, worker selection.

Do not introduce direct API-to-worker execution RPC as the default path. Direct RPC may be useful for diagnostics or administrative control later, but the primary execution path should remain queue/scheduler mediated so workers can scale horizontally and disappear without coupling API requests to a specific process.

## Non-decisions

This ADR does not choose a future database, queue, message broker, or service discovery technology.

This ADR does not require cross-host worker discovery in the current local Docker Compose implementation.

This ADR does not require graceful worker deregistration in the first adapter. Stale entries can be ignored by `last_seen` timeout.

This ADR does not remove worker-side runtime validation. Registry state improves API feedback but is not authoritative enough to skip execution-time checks.

## Consequences

### Positive

- Prevents API from coupling back to GPU worker runtime files or dependencies.
- Fixes current cross-container upscale availability misclassification with a small local adapter.
- Creates a migration path from JSON files to persistent database and distributed worker scheduling.
- Keeps the current local runtime simple while making future communication concepts explicit.
- Allows API to provide better user feedback before creating unschedulable jobs.

### Negative

- `workers.json` remains a local shared-filesystem adapter and is not a distributed registry.
- API schedulability checks may race with worker shutdown or runtime changes.
- Worker final validation remains required, so some failures can still occur after job acceptance.
- The project now has another runtime state file to maintain and test.

## Alternatives Considered

1. **API inspects worker runtime paths directly** — rejected because API and Worker are separate roles and may not share filesystem, dependencies, or hosts.
2. **API directly calls a Worker before creating every job** — rejected as the default because it couples request handling to a specific worker and does not scale cleanly to queue-based scheduling.
3. **Only let Worker fail jobs after acceptance** — simple but gives poor user feedback and misses an opportunity to establish the future registry boundary.
4. **Introduce Redis/Postgres/message broker now** — useful later, but premature for the current local Docker Compose phase.

## Related Documents

- [ADR 0001: Engine-oriented Product Runtime](0001-engine-oriented-product-runtime.md)
- [ADR 0003: Backend Runtime Contracts](0003-backend-runtime-contract.md)
- [Runtime Architecture](../runtime-architecture.md)
