# Resident Runtime Host — Real-Environment Acceptance Test Plan

> This document records the acceptance test matrix for validating the platform resident runtime host in a real GPU environment. Tests are ordered by priority: P0 (must pass before any further work), P1 (important lifecycle behaviors), P2 (long-running stability).

## Environment Requirements

- Docker with GPU access (via `scripts/docker-proxy.sh`)
- Model assets present under `MODEL_ROOT`
- Worker and API services running (`make build && make up`)

## P0: Primary Execution Chain

These tests verify that the resident runtime host is the active execution path and that jobs complete end-to-end.

### P0-1: Cold Start

- Submit first PanoWan job after worker startup
- Expected: job status transitions `queued → running → completed`
- Runtime status transitions: `cold → loading → warm → running → warm`
- Verify: output file created at `output_path`

### P0-2: Warm Reuse

- Submit a second job with the same runtime identity (same task, same model config)
- Expected: job completes without a full model reload
- Runtime status should remain `warm` throughout (no `loading` transition)
- Latency should be significantly lower than P0-1

### P0-3: Identity Change Reload

- Submit a job that changes runtime identity (e.g., different task type if supported)
- Expected: runtime evicts the current instance and loads a new one
- Runtime status transitions: `warm → evicting → cold → loading → warm`
- Job completes after reload

### P0-4: Consecutive Jobs

- Submit 3+ jobs of the same identity in sequence
- Expected: all complete successfully; runtime stays `warm`
- No increasing latency or degradation across runs

## P1: Failure and Recovery Behaviors

These tests verify that the runtime host correctly distinguishes job-scoped and runtime-corrupting failures, and that idle eviction works.

### P1-1: Job-Scoped Failure Does Not Poison Runtime

- Submit a job that fails for a business-input reason (e.g., bad payload field, missing optional resource)
- Expected: job status = `failed`, but runtime remains `warm`
- Next job with same identity should reuse the warm runtime (no reload)
- Verify: `panowan_runtime_status` stays `warm` after failure

### P1-2: Runtime-Corrupting Failure Triggers Reset

- Cause a runtime-corrupting error during execution (e.g., CUDA OOM, or simulate via provider `classify_runtime_failure`)
- Expected: current job fails; runtime enters `failed` state
- Host should perform reset/eviction back to `cold`
- Next job should trigger a fresh cold load and complete

### P1-3: Idle Eviction

- Set `PANOWAN_IDLE_EVICT_SECONDS` to a short value (e.g., 30)
- Submit a job, then wait past the idle threshold
- Expected: runtime transitions `warm → evicting → cold`
- Verify via worker registry: `panowan_runtime_status` changes to `cold`
- Next job should trigger a fresh cold load

### P1-4: Cancellation Propagation

- Submit a job, then cancel it while running
- Expected: `_should_cancel` is polled by the execution layer
- Job transitions to `cancelled`
- Runtime should not be poisoned (remains `warm` or returns to `warm`)
- No zombie processes or leaked GPU memory

## P2: Long-Running Stability

These tests verify behavior over extended operation.

### P2-1: Memory Stability Over Multiple Jobs

- Run 10+ consecutive jobs of the same identity
- Monitor GPU memory usage across runs
- Expected: no continuous VRAM growth; stable memory after warm reuse
- Runtime status remains `warm` throughout

### P2-2: Reload After Eviction Cleans Up

- Trigger idle eviction, then submit a new job
- Verify VRAM is freed during eviction, then re-allocated during load
- No leaked GPU memory from the previous warm instance

### P2-3: Worker Restart Recovery

- Restart the worker container while runtime is `warm`
- After restart, runtime should be `cold` (no stale state)
- First job after restart should cold-load and complete normally

## Test Results Log

| Test | Date | Result | Notes |
|------|------|--------|-------|
| P0-1 | 2026-04-30 | PASS | Job `97f4cb31`: cold start completed |
| P0-2 | 2026-04-30 | PASS | Job `b793cab6`: warm reuse, no reload |
| P0-3 | 2026-04-30 | N/A | Only one identity variant (t2v) tested so far |
| P0-4 | 2026-04-30 | PASS | Jobs `6738f05c`, `140aba7e`: consecutive completions |
| P1-1 | — | — | — |
| P1-2 | — | — | — |
| P1-3 | — | — | — |
| P1-4 | — | — | — |

## Known Issues Found During Testing

1. **Job record vs API payload contract drift** (fixed): `PanoWanEngine.run` was passing the full job record to `build_runner_payload` instead of the API-originated payload sub-dict. Fixed in `app/engines/panowan.py`.

2. **`negative_prompt` required constraint**: Both API (`app/api.py`) and runner contract (`runtime_adapter.py`) enforce `negative_prompt` as required, but it should accept empty strings. Tracked for fix.

3. **API `/health` reports `model_ready=false` in container**: The health endpoint checks local filesystem paths that are not mounted into the API container. This does not block execution but misrepresents system readiness.

4. **`make doctor` host Python/Docker entry**: `scripts/doctor.sh` and `scripts/lib/env.sh` used `python3` and direct `docker` instead of project conventions. Fixed to use `uv run python` and `scripts/docker-proxy.sh`.
