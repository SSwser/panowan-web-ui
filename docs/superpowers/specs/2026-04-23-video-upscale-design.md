# Video Upscale Feature Design

## Overview

Add video super-resolution (upscale) capability to panowan-worker. Users can upscale completed video generation jobs to higher resolution using one of three supported models. Upscaled results are stored as independent jobs linked to their source. The preview window supports three comparison modes (side-by-side, A/B toggle, slider). An SSE endpoint replaces polling for real-time job status updates. A cancel endpoint allows terminating queued or running jobs.

## 1. Data Model

### Job Record Extensions

Existing job record gains three new fields:

```python
{
    # ... existing fields unchanged ...
    "job_id": str,
    "status": str,           # "queued" | "running" | "completed" | "failed"
    "prompt": str,
    "params": dict,
    "output_path": str,
    "download_url": str,
    "created_at": str,
    "started_at": str | None,
    "finished_at": str | None,
    "error": str | None,

    # ===== New fields =====
    "type": str,             # "generate" | "upscale", default "generate"
    "source_job_id": str | None,  # For upscale jobs: linked source job_id. None for generate.
    "upscale_params": dict | None # Upscale parameters, only set when type="upscale"
}
```

### Upscale Params Structure

```python
"upscale_params": {
    "model": str,              # "realesrgan-animevideov3" | "realbasicvsr" | "seedvr2-3b"
    "scale": int,              # 2 or 4
    "target_width": int | None,   # Optional, takes priority over scale
    "target_height": int | None,  # Optional, takes priority over scale
}
```

### Backward Compatibility

All existing job records are auto-migrated on restore: `type` defaults to `"generate"`, `source_job_id` and `upscale_params` default to `None`. The existing `POST /generate` endpoint behavior is unchanged.

## 2. API Endpoints

### New: `POST /upscale`

Submit an upscale job for a completed generation job.

**Request body:**

```json
{
    "source_job_id": "abc123",
    "model": "realesrgan-animevideov3",
    "scale": 2,
    "target_width": null,
    "target_height": null
}
```

- `source_job_id` (required): must exist, be `completed`, have output file present, and be of type `generate` or `upscale` (upscale jobs can be chained)
- `model` (optional): defaults to `"realesrgan-animevideov3"`, must be in supported list
- `scale` (optional): defaults to model's default scale
- `target_width`/`target_height` (optional): if provided, takes priority over `scale`; at least one of `scale` or target dimensions must be provided

**Response (202):**

```json
{
    "job_id": "def456",
    "status": "queued",
    "type": "upscale",
    "source_job_id": "abc123",
    "upscale_params": { "model": "realesrgan-animevideov3", "scale": 2 }
}
```

**Validation errors (400):**
- Source job not found, not completed, or output file missing
- Model not in supported list
- Scale exceeds model's max_scale
- Model-specific constraints (e.g., SeedVR2 requires target dimensions multiples of 32, RealBasicVSR only supports 4x)
- Neither scale nor target dimensions provided

### New: `POST /jobs/{job_id}/cancel`

Cancel a queued or running job.

**Request body:**

```json
{
    "force": false
}
```

**Behavior matrix:**

| Job status | `force=false` (default) | `force=true` |
|---|---|---|
| `queued` | Mark as `failed`, error: "Cancelled by user". Return 200. | Same |
| `running` | Return 202 with warning. **No cancel executed.** | Execute two-phase termination, then mark `failed`. Return 200. |
| `completed`/`failed` | Return 409 | Return 409 |

**Running + force=false response (202):**

```json
{
    "job_id": "abc123",
    "status": "running",
    "warning": "Job is currently running. Force termination may cause incomplete output. Set force=true to confirm.",
    "pid": 12345
}
```

**Running + force=true two-phase termination:**

1. SIGTERM, wait up to 5 seconds
2. If process exits: cleanup temp files, mark `failed`, return 200
3. If timeout: SIGKILL, wait up to 3 seconds
4. If process exits: cleanup temp files, mark `failed`, return 200
5. If process still alive: mark `failed` with error "Cancel failed: process unkillable", return 500

**Frontend interaction flow:**
1. User clicks "Cancel" on a `queued` job: call `cancel(force=false)`, immediate cancel
2. User clicks "Cancel" on a `running` job: show confirmation dialog about force termination
3. User confirms: call `cancel(force=true)`
4. Frontend polls job status, waiting for `failed` (success) or persistent `running` (failure, show error)

### New: `GET /jobs/events` (SSE)

Server-Sent Events endpoint for real-time job status updates.

**Event types:**

| Event | Trigger | Data |
|---|---|---|
| `job_created` | New job created | Full job record |
| `job_updated` | Job status/attributes changed | Changed fields (incremental patch) |
| `heartbeat` | Every 30 seconds | `{"ts": "ISO8601"}` |

**Event format:**

```
event: job_updated
data: {"job_id":"abc123","status":"running","started_at":"2026-04-23T..."}

event: heartbeat
data: {"ts":"2026-04-23T12:00:00Z"}
```

### Modified: `GET /jobs`, `GET /jobs/{job_id}`

Response for each job includes the new fields: `type`, `source_job_id`, `upscale_params`.

### Unchanged: `GET /jobs/{job_id}/download`

Works for both generate and upscale jobs. Upscale job's download_url points to the upscaled video.

## 3. Frontend UI

### 3.1 Job List Changes

**New action buttons by job type/status:**

| Job type/status | Actions |
|---|---|
| `generate` + `completed` | Existing preview + download, **new "Upscale" button** |
| `upscale` + `completed` | Preview (with comparison modes) + **two download links** (original + upscaled) + source job tag (e.g., `source: abc123`) + **"Upscale" button** (can upscale an already-upscaled video) |
| `queued` (any type) | **"Cancel" button** |
| `running` (any type) | **"Cancel" button** (triggers confirmation dialog for force termination) |

**Download for upscale jobs:**
- "Download Original" -> downloads source job's output via `/jobs/{source_job_id}/download`
- "Download Upscaled" -> downloads current job's output via `/jobs/{job_id}/download`

### 3.2 Upscale Configuration Dialog

Triggered by clicking "Upscale" on a completed generate job. Uses native `<dialog>`.

```
+-----------------------------------------+
|  Upscale Video                      [X] |
+-----------------------------------------+
|  Source: #abc123                        |
|  Original: 448x224                      |
|                                         |
|  Model:                                 |
|  [Real-ESRGAN (Fast)              v]    |
|                                         |
|  Scale mode:                            |
|  (o) By factor  ( ) Target resolution   |
|                                         |
|  Scale: [2x v]                          |
|  Target: W [____] x H [____]           |
|                                         |
|         [ Cancel ]  [ Start Upscale ]   |
+-----------------------------------------+
```

- Model dropdown: `Real-ESRGAN (Fast)` / `RealBasicVSR (High Quality)` / `SeedVR2-3B (SOTA)`
- Scale mode toggle shows/hides corresponding input group
- When specifying target resolution, auto-calculate scale factor, validate max 4x
- Model-specific constraints shown as helper text (e.g., "RealBasicVSR only supports 4x")

### 3.3 Preview Comparison Window

For `upscale` type completed jobs, the existing preview `<dialog>` is extended with a tab bar for comparison modes.

**Tab bar:**

```
[ Side by Side ]  [ A/B Toggle ]  [ Slider ]
```

For `generate` type jobs, preview works as before (no tabs, single video).

**Side-by-Side mode:**
- Two `<video>` elements side by side: original (left) + upscaled (right)
- Synchronized playback: play/pause/seek on one controls both
- Resolution labels below each video

**A/B Toggle mode:**
- Single `<video>` element
- [A Original] and [B Upscaled] toggle buttons
- Switching preserves playback position and state
- Keyboard shortcut: `A` key / `B` key for quick toggle

**Slider mode:**
- Paused at current frame (static comparison)
- CSS clip-based left/right split view on canvas
- Draggable slider divider
- Frame navigation: previous/next frame buttons
- Both videos rendered to same canvas resolution for pixel-level comparison

## 4. Backend Upscaler Module

### 4.1 Upscaler Interface

New file `app/upscaler.py` defines a Protocol and three implementations:

```python
from typing import Protocol

class UpscalerBackend(Protocol):
    name: str
    display_name: str
    default_scale: int
    max_scale: int

    def build_command(
        self,
        input_path: str,
        output_path: str,
        scale: int,
        target_width: int | None,
        target_height: int | None,
        model_dir: str,
    ) -> list[str]: ...

    def validate_params(self, scale: int, source_w: int, source_h: int) -> str | None: ...
```

### 4.2 Backend Implementations

**RealESRGANBackend:**
- `name`: `"realesrgan-animevideov3"`
- `display_name`: `"Real-ESRGAN (Fast)"`
- `default_scale`: 2, `max_scale`: 4
- Command: `python inference_realesrgan_video.py -i <input> -o <output_dir> -n realesr-animevideov3 -s <scale> --half`
- Deployment: `pip install realesrgan`
- License: BSD-3-Clause
- VRAM: ~2-4GB
- Limitation: frame-by-frame processing, no temporal consistency

**RealBasicVSRBackend:**
- `name`: `"realbasicvsr"`
- `display_name`: `"RealBasicVSR (High Quality)"`
- `default_scale`: 4, `max_scale`: 4 (only supports 4x)
- Command: `python inference_realbasicvsr.py <config> <checkpoint> <input> <output> --max-seq-len 30`
- Deployment: `pip install openmim && mim install mmagic`
- License: Apache-2.0
- VRAM: ~8-12GB
- Strength: bidirectional propagation for temporal consistency

**SeedVR2Backend:**
- `name`: `"seedvr2-3b"`
- `display_name`: `"SeedVR2-3B (SOTA)"`
- `default_scale`: 2, `max_scale`: 4
- Command: `torchrun --nproc_per_node=1 projects/inference_seedvr2_3b.py --video_path <dir> --output_dir <dir> --res_h <h> --res_w <w> --sp_size 1`
- Deployment: git clone + manual install (no pip package)
- License: Apache-2.0
- VRAM: 24GB+ (FP16), 12GB+ (FP8)
- Constraint: target dimensions must be multiples of 32
- Strength: single-step diffusion transformer, best perceptual quality

### 4.3 Model Registry

```python
UPSCALE_BACKENDS: dict[str, UpscalerBackend] = {
    "realesrgan-animevideov3": RealESRGANBackend(),
    "realbasicvsr": RealBasicVSRBackend(),
    "seedvr2-3b": SeedVR2Backend(),
}
```

### 4.4 Job Execution

New `_run_upscale_job()` function parallel to existing `_run_generation_job()`:

1. Fetch job and source_job from `_jobs`
2. Validate source_job output file exists
3. Set status `running`, record `started_at`
4. Acquire GPU semaphore (shared with generate: `Semaphore(1)`)
5. Store Popen process in `job["_process"]` (memory only, not persisted)
6. Call `upscaler.upscale_video(...)`
7. Update `output_path`, `download_url`
8. Set status `completed`, record `finished_at`
9. On exception: set status `failed`, record `error`
10. Release GPU semaphore
11. Persist to disk

### 4.5 Cancel Logic

```python
def cancel_job(job_id: str, force: bool = False):
    job = _jobs.get(job_id)
    if job["status"] == "queued":
        job["status"] = "failed"
        job["error"] = "Cancelled by user"
    elif job["status"] == "running" and force:
        process = job.get("_process")
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            _cleanup_upscale_temp(job)
        job["status"] = "failed"
        job["error"] = "Cancelled by user"
    elif job["status"] == "running" and not force:
        process = job.get("_process")
        return {"warning": True, "status": "running", "pid": process.pid if process else None}

**Note on `_process` access:** The `_process` field is a `subprocess.Popen` object stored in memory only (not persisted). There is a brief window between status being set to `running` and `_process` being stored. If cancel is called during this window, `_process` will be `None`. In this case, the cancel for `running` + `force=true` should still mark the job as `failed` but skip the termination step, as the Popen hasn't been created yet. The background task wrapper should check for cancellation before starting the subprocess.
```

### 4.6 Settings Extensions

```python
# app/settings.py new fields
upscale_model_dir: str = "/app/data/models/upscale"
upscale_output_dir: str = "/app/runtime/outputs"
upscale_timeout_seconds: int = 1800
```

### 4.7 Subprocess Change

Both `generate_video()` and upscale execution switch from `subprocess.run()` to `subprocess.Popen` to support cancel. The Popen object is stored in `job["_process"]` (memory, not persisted to JSON).

## 5. SSE Real-time Updates

### 5.1 Strategy: Hybrid Mode

- **Initial load**: `GET /jobs` for full list (fast first paint)
- **Incremental updates**: SSE pushes changed jobs, frontend merges into `_jobCache`
- **Fallback**: On SSE disconnect, revert to 5s polling; on SSE reconnect, do one `GET /jobs` full sync then resume SSE

### 5.2 Backend Implementation

Uses `sse-starlette` package. A global list of `asyncio.Queue` subscribers. On job state change, `_broadcast_job_event()` pushes to all subscribers. Heartbeat every 30s keeps connection alive.

### 5.3 Frontend Implementation

Native `EventSource` API. `JobEventSource` class manages connection lifecycle:

- `connect()`: establish SSE, listen for `job_created` and `job_updated` events
- On event: merge into `_jobCache`, trigger incremental `renderTable()`
- `onerror`: close SSE, start 5s fallback polling, schedule reconnect in 5s
- On reconnect: stop polling, do `GET /jobs` full sync, resume SSE

### 5.4 Polling Migration

| Phase | Behavior |
|---|---|
| Page load | `GET /jobs` full load -> render -> establish SSE |
| SSE connected | Listen for events, incremental updates |
| SSE disconnected | Fallback to 5s polling, schedule reconnect |
| SSE reconnected | Stop polling, full sync via `GET /jobs`, resume SSE |

### 5.5 Dependency

- Backend: `sse-starlette` (`pip install sse-starlette`)
- Frontend: native `EventSource` API (zero dependency)

## 6. Error Handling

### 6.1 Upscale-Specific Errors

| Scenario | Handling |
|---|---|
| Source job output file deleted | `POST /upscale` returns 400: "Source video file not found" |
| Source job not completed | `POST /upscale` returns 400: "Can only upscale completed jobs" |
| Scale exceeds model limit | `POST /upscale` returns 400, validated by `validate_params()` |
| SeedVR2 target resolution not multiple of 32 | `POST /upscale` returns 400 |
| RealBasicVSR non-4x scale | `POST /upscale` returns 400 |
| Subprocess timeout | Mark `failed`, error: "Upscale timed out after {timeout}s" |
| Subprocess non-zero exit | Mark `failed`, error includes last 500 chars of stderr |
| Output file missing after process exit | Mark `failed`, error: "Upscale completed but output file missing" |
| GPU OOM | Subprocess killed by system, normal failure flow; detect "CUDA out of memory" in stderr for friendly message |

### 6.2 Concurrency & Race Conditions

| Scenario | Handling |
|---|---|
| Multiple upscales on same source | Allowed, each is independent job, queued |
| Source output deleted during upscale | Subprocess fails, normal failure flow |
| Cancel vs natural completion race | `_jobs_lock` protects: check status before operating |
| Service restart with running upscale | Same as generate: `running` -> `failed` (cannot resume subprocess) |

### 6.3 Resource Cleanup

| Scenario | Strategy |
|---|---|
| Temp frame files (Real-ESRGAN, SeedVR2) | Normal exit: cleaned by subprocess. Cancel/crash: `_cleanup_upscale_temp()` scans and deletes |
| Failed job output files | Retained on disk (consistent with generate behavior) |
| SSE subscriber disconnect | `finally` block removes from subscriber list |

### 6.4 Frontend Error Handling

| Scenario | Handling |
|---|---|
| SSE connection failure | Console warning, fallback to polling |
| Upscale request 400 | Dialog showing error message |
| Cancel running job failure | Error toast: "Cancel failed, please retry" |
| Source video load failure (comparison) | Placeholder: "Video load failed" |
| Slider mode video not buffered | Loading state, render after buffer complete |

## 7. Concurrency Model

GPU concurrency is managed by `_gpu_slot = threading.Semaphore(1)`. Both generate and upscale jobs share this single slot. PanoWan (`panowan-test` CLI) is a single-GPU single-process inference tool; running two instances simultaneously would cause GPU OOM. Therefore, all GPU tasks execute serially in submission order.

Future path for concurrency:
- Multi-GPU: `Semaphore(N)` with `CUDA_VISIBLE_DEVICES` binding per job
- Async inference: requires PanoWan source code modification

## 8. Plugin Framework Assessment

Not introduced in this version. Three backends registered via Protocol interface + dict is sufficient. Adding a new backend requires: implement `UpscalerBackend`, register in `UPSCALE_BACKENDS`, add model weights. Three steps, no framework overhead.

Trigger for future pluginization:
- Backend count exceeds 5-6
- Non-subprocess integration needed (e.g., direct Python API calls)
- User-authored custom backends without source modification
