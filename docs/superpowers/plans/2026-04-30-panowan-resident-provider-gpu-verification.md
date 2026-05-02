# PanoWan Resident Provider — GPU End-to-End Verification

**Status:** waiting on operator (requires WSL + NVIDIA GPU + Docker).
**Context:** the resident runtime provider was wired from stub to real `diffsynth` inference. Host unit tests pass with a fake `diffsynth` harness. The contract now requires a real `WanVideoPipeline` build + `save_video()` call, so a "completed" job means a non-empty mp4 was actually produced. This plan covers the operator-side verification that cannot run on the Windows host.

## What changed

| File | Change |
| --- | --- |
| `third_party/PanoWan/sources/runtime_provider.py` | Stub `Path(...).touch()` replaced with real `ModelManager.load_models(...)` → `WanVideoPipeline.from_model_manager(...)` → `enable_vram_management(num_persistent_param_in_dit=None)` → `pipe(...)` → `save_video(...)`. Lazy-imports `diffsynth`/`torch` after injecting `vendor/src` onto `sys.path`. Rejects `task != "t2v"` (upstream ships only the t2v pipeline) and rejects non-panoramic resolutions (`width != 2 * height`). |
| `third_party/PanoWan/runner.py` | CLI now delegates to the provider (`load_resident_runtime` → `run_job_inprocess` → `teardown_resident_runtime`). Spec §9: CLI and resident execution must share dispatch. |
| `third_party/PanoWan/backend.toml` | `[runtime_inputs] files` adds `runtime_provider.py`; `[weights] required_files` adds `Wan-AI/Wan2.1-T2V-1.3B/Wan2.1_VAE.pth`. |
| `app/backends/model_specs.py` | `wan-t2v-1.3b` spec adds `Wan2.1_VAE.pth` so `make setup-backends` actually downloads the file the pipeline loads. |
| `tests/test_panowan_runtime_provider.py` | Rewritten with a fake `diffsynth` + fake `torch` harness so the provider's wiring contract is testable on the host. |

Host suite: `uv run python -m unittest discover -s tests` → **281 passed**.

## Operator prerequisites (one-time)

1. WSL with Docker + NVIDIA Container Toolkit (`make doctor` should be green for GPU).
2. `make setup-backends` — clones `https://github.com/SSwser/PanoWan` into `third_party/PanoWan/vendor/`. After this, `third_party/PanoWan/vendor/src/diffsynth/__init__.py` must exist; the provider's `_ensure_vendor_on_sys_path()` will refuse to load otherwise.
3. Confirm weights exist under `$MODEL_ROOT`:
   - `Wan-AI/Wan2.1-T2V-1.3B/diffusion_pytorch_model.safetensors`
   - `Wan-AI/Wan2.1-T2V-1.3B/models_t5_umt5-xxl-enc-bf16.pth`
   - `Wan-AI/Wan2.1-T2V-1.3B/Wan2.1_VAE.pth`  ← previously missing from spec
   - `PanoWan/latest-lora.ckpt`

   If `Wan2.1_VAE.pth` is missing on a pre-existing install, re-run `make setup-backends` or `uv run -m app.backends install` to reconcile against the updated spec.

## Verification matrix

Run from the project root after `make build && make up` (or `make up DEV=1`).

### V1 — Cold start produces a real mp4

1. `curl -X POST http://localhost:8000/v1/jobs -H 'content-type: application/json' -d '{"type":"generate","payload":{"task":"t2v","prompt":"sunset over mountains","negative_prompt":"blur","resolution":{"width":896,"height":448},"num_frames":81,"num_inference_steps":25,"seed":7}}'`
2. Stream SSE: `curl -N http://localhost:8000/v1/jobs/<id>/events`
3. Expected:
   - Worker telemetry transitions: `cold → loading → warm → running → warm`
   - Job `status` ends `completed`
   - File at returned `output_path` exists with **non-zero size** (`ls -l` from inside the worker container or via the mounted `data/runtime/outputs/` host volume).
   - mp4 is playable (e.g. `ffprobe`).

   **Failure means the wiring is wrong** — previously the stub left a 0-byte file but reported `completed`.

### V2 — Warm reuse skips reload

1. Submit a second t2v job with the same identity (same model_dir, same lora_path) within the idle window.
2. Expected: no second `loading` transition; provider reuses the cached `WanVideoPipeline`. SSE shows `running` directly after `warm`.

### V3 — Idle eviction

1. After V2, leave the worker idle past `RESIDENT_RUNTIME_IDLE_SECONDS` (default in `app/settings.py`).
2. Expected log: `PanoWan runtime evicted after >= Ns idle.` Next job re-runs `loading`.

### V4 — Invalid input is rejected before GPU work

1. Submit t2v with `resolution.width != 2 * resolution.height` (e.g. 512×512).
2. Expected: job `failed` with `InvalidRunnerJob`-classified error; no GPU memory allocated.

### V5 — i2v rejection

1. Submit `task: "i2v"`.
2. Expected: job `failed` with message containing "upstream diffsynth ships only the t2v pipeline". This is intentional until upstream ships an i2v pipeline.

## Known operator-side blockers

- **flash-attn build**: upstream `diffsynth` pins `torch~=2.9.1` with `flash-attn`. First container build can take a while; if it OOMs, set `MAX_JOBS=2` in the build env.
- **VRAM**: `enable_vram_management(num_persistent_param_in_dit=None)` keeps the DiT off-VRAM between calls. For ≤ 12 GB cards this is required; for ≥ 24 GB you may pass an integer for faster inference.
- **Windows host**: this verification cannot run on the Windows host directly — all `docker`/GPU paths go through WSL via `make` / `scripts/docker-proxy.sh` per AGENTS.md.

## Sign-off

When V1–V5 all pass, this plan can be deleted (per `AGENTS.md` documentation lifecycle: plans are temporary).
