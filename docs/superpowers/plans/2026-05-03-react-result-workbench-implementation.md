# React Result Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy single-file HTML UI with a React TypeScript result workbench that centers 360° result preview, version comparison, upscaling, and task governance.

**Architecture:** Keep backend jobs as the execution model, but expose a new result/version product model under `/api`. Add an independent `frontend/` Vite React TypeScript app that consumes result/version APIs, renders the desktop-first workbench, and uses a project-owned `three` + `@react-three/fiber` panorama viewer. Remove the legacy HTML UI as the primary frontend instead of preserving compatibility shims.

**Tech Stack:** FastAPI, Python `unittest`, Vite, React 18, TypeScript, Vitest, Testing Library, Playwright, `three`, `@react-three/fiber`, CSS modules or plain CSS tokens.

---

## File Structure Map

### Backend files

- Modify: `app/api.py`
  - Add `/api/results`, `/api/results/{result_id}`, `/api/results/{result_id}/versions/{version_id}/upscale`, `/api/runtime/summary`, and `/api/events`.
  - Keep job governance endpoints around job IDs.
  - Serve React build at root.

- Create: `app/result_views.py`
  - Convert raw job records into `ResultSummary` and `ResultVersion` dictionaries.
  - Own all result/version naming, ordering, status aggregation, and parent-child mapping.

- Modify: `app/settings.py`
  - Add `frontend_dist_dir` derived from repo root so FastAPI can serve `frontend/dist`.

- Modify: `app/paths.py`
  - Expose a repo-root helper if the existing helper cannot be reused cleanly from settings or API.

- Modify: `tests/test_api.py`
  - Add API contract coverage for results, upscaling versions, runtime summary, and result-aware events.

- Modify: `tests/test_static_ui.py`
  - Replace legacy static HTML assertions with checks that the FastAPI root is wired to the React build behavior.

### Frontend files

- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/types/result.ts`
- Create: `frontend/src/types/runtime.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/resultClient.ts`
- Create: `frontend/src/api/runtimeClient.ts`
- Create: `frontend/src/api/eventClient.ts`
- Create: `frontend/src/stores/resultStore.ts`
- Create: `frontend/src/stores/runtimeStore.ts`
- Create: `frontend/src/stores/workspaceStore.ts`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/RuntimeStatusBar.tsx`
- Create: `frontend/src/components/StatusPill.tsx`
- Create: `frontend/src/features/create/CreateTaskPanel.tsx`
- Create: `frontend/src/features/results/ResultPreviewWorkspace.tsx`
- Create: `frontend/src/features/results/VersionStrip.tsx`
- Create: `frontend/src/features/results/ResultMetadataBar.tsx`
- Create: `frontend/src/features/viewer/PanoVideoViewer.tsx`
- Create: `frontend/src/features/viewer/ViewerControls.tsx`
- Create: `frontend/src/features/viewer/SyncedPanoramaCompare.tsx`
- Create: `frontend/src/features/viewer/ABPanoramaCompare.tsx`
- Create: `frontend/src/features/viewer/SliderPanoramaCompare.tsx`
- Create: `frontend/src/features/versions/VersionUpscalePanel.tsx`
- Create: `frontend/src/features/versions/UpscaleForm.tsx`
- Create: `frontend/src/features/tasks/RecentTasksTable.tsx`
- Create: `frontend/src/features/tasks/TaskActionsMenu.tsx`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/app.css`
- Create: `frontend/src/test/setup.ts`
- Create tests beside the frontend files using `*.test.ts` or `*.test.tsx`.

### Deleted or deprecated files

- Delete after React root integration is complete: `app/static/index.html`
- Delete or rewrite after React tests exist: legacy assertions in `tests/test_static_ui.py`

---

## Task 1: Backend result/version projection module

**Files:**
- Create: `app/result_views.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add failing tests for result/version projection**

Append these tests inside `ApiTests` in `tests/test_api.py`:

```python
    def test_result_view_groups_generate_and_upscale_jobs(self) -> None:
        from app.result_views import build_result_summaries

        generate = api._create_job_record(
            "job-generate-1",
            "A cinematic alpine valley at sunset",
            os.path.join(self.temp_dir.name, "outputs", "job-generate-1.mp4"),
            {"num_inference_steps": 50, "width": 896, "height": 448, "seed": 0},
        )
        api.get_job_backend().update_job(
            generate["job_id"],
            status="succeeded",
            finished_at="2026-05-02T12:13:00Z",
        )
        upscale = api._create_job_record(
            "job-upscale-1",
            generate["prompt"],
            os.path.join(self.temp_dir.name, "outputs", "job-upscale-1.mp4"),
            generate["params"],
            job_type="upscale",
            source_job_id=generate["job_id"],
            upscale_params={"model": "seedvr2", "scale": 4, "width": 3584, "height": 1792},
            payload={"source_job_id": generate["job_id"]},
        )
        api.get_job_backend().update_job(
            upscale["job_id"],
            status="queued",
            created_at="2026-05-02T12:14:00Z",
        )

        summaries = build_result_summaries(api.get_job_backend().list_jobs())

        self.assertEqual(len(summaries), 1)
        result = summaries[0]
        self.assertEqual(result["result_id"], "res_job-generate-1")
        self.assertEqual(result["root_job_id"], "job-generate-1")
        self.assertEqual(result["prompt"], "A cinematic alpine valley at sunset")
        self.assertEqual(result["status"], "mixed")
        self.assertEqual([version["version_id"] for version in result["versions"]], ["ver_job-generate-1", "ver_job-upscale-1"])
        self.assertEqual(result["versions"][0]["type"], "original")
        self.assertEqual(result["versions"][1]["type"], "upscale")
        self.assertEqual(result["versions"][1]["parent_version_id"], "ver_job-generate-1")
        self.assertEqual(result["versions"][1]["label"], "4x SeedVR2")

    def test_result_view_exposes_failed_result_status(self) -> None:
        from app.result_views import build_result_summaries

        record = api._create_job_record(
            "job-generate-failed",
            "A failed prompt",
            os.path.join(self.temp_dir.name, "outputs", "job-generate-failed.mp4"),
            {"num_inference_steps": 20, "width": 448, "height": 224},
        )
        api.get_job_backend().update_job(
            record["job_id"],
            status="failed",
            error="runtime failed",
            finished_at="2026-05-02T12:15:00Z",
        )

        summaries = build_result_summaries(api.get_job_backend().list_jobs())

        self.assertEqual(summaries[0]["status"], "failed")
        self.assertEqual(summaries[0]["versions"][0]["error"], "runtime failed")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_result_view_groups_generate_and_upscale_jobs tests.test_api.ApiTests.test_result_view_exposes_failed_result_status
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.result_views'`.

- [ ] **Step 3: Create `app/result_views.py`**

Create `app/result_views.py` with this content:

```python
from __future__ import annotations

from collections import defaultdict
from typing import Any

TERMINAL_SUCCESS = {"succeeded", "completed"}
ACTIVE_STATUSES = {"queued", "claimed", "running", "cancelling"}
FAILED_STATUSES = {"failed"}
CANCELLED_STATUSES = {"cancelled"}


def build_result_summaries(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs_by_id = {str(job.get("job_id")): job for job in jobs if job.get("job_id")}
    root_by_job: dict[str, str] = {}

    for job_id, job in jobs_by_id.items():
        root_by_job[job_id] = _root_job_id(job, jobs_by_id)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job_id, job in jobs_by_id.items():
        grouped[root_by_job[job_id]].append(job)

    summaries = [_build_result_summary(root_job_id, group, jobs_by_id) for root_job_id, group in grouped.items()]
    summaries.sort(key=lambda result: str(result.get("updated_at") or result.get("created_at") or ""), reverse=True)
    return summaries


def build_result_summary(result_id: str, jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    summaries = build_result_summaries(jobs)
    for summary in summaries:
        if summary["result_id"] == result_id:
            return summary
    return None


def version_id_for_job(job_id: str) -> str:
    return f"ver_{job_id}"


def result_id_for_root_job(job_id: str) -> str:
    return f"res_{job_id}"


def _root_job_id(job: dict[str, Any], jobs_by_id: dict[str, dict[str, Any]]) -> str:
    current = job
    seen: set[str] = set()
    while current.get("source_job_id"):
        source_id = str(current["source_job_id"])
        if source_id in seen or source_id not in jobs_by_id:
            return source_id
        seen.add(source_id)
        current = jobs_by_id[source_id]
    return str(current.get("job_id"))


def _build_result_summary(root_job_id: str, jobs: list[dict[str, Any]], jobs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root_job = jobs_by_id.get(root_job_id) or min(jobs, key=_created_at)
    versions = [_build_version(job, jobs_by_id) for job in sorted(jobs, key=_created_at)]
    status = _aggregate_status([str(version["status"]) for version in versions])
    updated_at = max(str(job.get("finished_at") or job.get("updated_at") or job.get("created_at") or "") for job in jobs)
    selected_version = _selected_version(versions)
    return {
        "result_id": result_id_for_root_job(root_job_id),
        "root_job_id": root_job_id,
        "prompt": root_job.get("prompt", ""),
        "negative_prompt": root_job.get("payload", {}).get("negative_prompt", ""),
        "status": status,
        "selected_version_id": selected_version.get("version_id") if selected_version else None,
        "created_at": root_job.get("created_at"),
        "updated_at": updated_at,
        "versions": versions,
    }


def _build_version(job: dict[str, Any], jobs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    job_id = str(job["job_id"])
    source_job_id = job.get("source_job_id")
    upscale_params = job.get("upscale_params") or {}
    params = job.get("params") or {}
    is_upscale = job.get("type") == "upscale" or bool(source_job_id)
    width = upscale_params.get("width") or params.get("width")
    height = upscale_params.get("height") or params.get("height")
    return {
        "version_id": version_id_for_job(job_id),
        "job_id": job_id,
        "parent_version_id": version_id_for_job(str(source_job_id)) if source_job_id else None,
        "type": "upscale" if is_upscale else "original",
        "label": _version_label(job, upscale_params),
        "status": job.get("status", "queued"),
        "model": upscale_params.get("model"),
        "scale": upscale_params.get("scale"),
        "width": width,
        "height": height,
        "duration_seconds": job.get("duration_seconds"),
        "fps": job.get("fps"),
        "bitrate_mbps": job.get("bitrate_mbps"),
        "file_size_bytes": job.get("file_size_bytes"),
        "thumbnail_url": job.get("thumbnail_url"),
        "preview_url": job.get("download_url"),
        "download_url": job.get("download_url"),
        "params": params,
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
    }


def _version_label(job: dict[str, Any], upscale_params: dict[str, Any]) -> str:
    if job.get("type") != "upscale" and not job.get("source_job_id"):
        return "原始生成"
    scale = upscale_params.get("scale")
    model = str(upscale_params.get("model") or "Upscale")
    display_model = " ".join(part.capitalize() for part in model.replace("-", " ").split())
    return f"{scale}x {display_model}" if scale else display_model


def _aggregate_status(statuses: list[str]) -> str:
    unique = set(statuses)
    if len(unique) == 1:
        return _result_status(statuses[0])
    if unique & ACTIVE_STATUSES and unique & (TERMINAL_SUCCESS | FAILED_STATUSES | CANCELLED_STATUSES):
        return "mixed"
    if unique <= TERMINAL_SUCCESS:
        return "completed"
    if unique <= FAILED_STATUSES:
        return "failed"
    if unique <= CANCELLED_STATUSES:
        return "cancelled"
    if unique & ACTIVE_STATUSES:
        return "running"
    return "mixed"


def _result_status(status: str) -> str:
    if status in TERMINAL_SUCCESS:
        return "completed"
    if status in FAILED_STATUSES:
        return "failed"
    if status in CANCELLED_STATUSES:
        return "cancelled"
    if status in ACTIVE_STATUSES:
        return "running" if status in {"claimed", "running", "cancelling"} else "queued"
    return status


def _selected_version(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    completed = [version for version in versions if version.get("status") in TERMINAL_SUCCESS]
    if completed:
        return completed[-1]
    return versions[-1] if versions else None


def _created_at(job: dict[str, Any]) -> str:
    return str(job.get("created_at") or "")
```

- [ ] **Step 4: Run projection tests and verify pass**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_result_view_groups_generate_and_upscale_jobs tests.test_api.ApiTests.test_result_view_exposes_failed_result_status
```

Expected: PASS.

- [ ] **Step 5: Commit backend projection**

Run:

```bash
rtk git add app/result_views.py tests/test_api.py && rtk git commit -m "feat: add result version projection"
```

---

## Task 2: New result and runtime API endpoints

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing API endpoint tests**

Append these tests inside `ApiTests` in `tests/test_api.py`:

```python
    def test_post_api_results_creates_result_view(self) -> None:
        response = self.client.post(
            "/api/results",
            json={
                "prompt": "A cinematic alpine valley at sunset",
                "negative_prompt": "overexposed, static",
                "quality": "standard",
                "params": {"num_inference_steps": 50, "width": 896, "height": 448, "seed": 0},
            },
        )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["result"]["prompt"], "A cinematic alpine valley at sunset")
        self.assertEqual(body["result"]["status"], "queued")
        self.assertEqual(len(body["result"]["versions"]), 1)
        self.assertEqual(body["result"]["versions"][0]["type"], "original")

    def test_get_api_results_lists_result_views(self) -> None:
        api._create_job_record(
            "job-generate-1",
            "A cinematic alpine valley at sunset",
            os.path.join(self.temp_dir.name, "outputs", "job-generate-1.mp4"),
            {"num_inference_steps": 50, "width": 896, "height": 448},
        )

        response = self.client.get("/api/results")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["results"][0]["result_id"], "res_job-generate-1")
        self.assertEqual(body["results"][0]["versions"][0]["version_id"], "ver_job-generate-1")

    def test_get_api_result_returns_404_for_missing_result(self) -> None:
        response = self.client.get("/api/results/res_missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Result not found")

    def test_api_runtime_summary_uses_workbench_field_names(self) -> None:
        self._seed_upscale_worker()

        response = self.client.get("/api/runtime/summary")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["capacity"], 1)
        self.assertEqual(body["available_capacity"], 1)
        self.assertEqual(body["online_workers"], 1)
        self.assertEqual(body["loading_workers"], 0)
        self.assertEqual(body["busy_workers"], 0)
        self.assertEqual(body["queued_jobs"], 0)
        self.assertEqual(body["running_jobs"], 0)
        self.assertEqual(body["cancelling_jobs"], 0)
        self.assertTrue(body["runtime_warm"])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_post_api_results_creates_result_view tests.test_api.ApiTests.test_get_api_results_lists_result_views tests.test_api.ApiTests.test_get_api_result_returns_404_for_missing_result tests.test_api.ApiTests.test_api_runtime_summary_uses_workbench_field_names
```

Expected: FAIL with 404 responses for new `/api` endpoints.

- [ ] **Step 3: Add API imports in `app/api.py`**

Modify the imports in `app/api.py` to include the projection helpers:

```python
from .result_views import (
    build_result_summaries,
    build_result_summary,
    result_id_for_root_job,
    version_id_for_job,
)
```

- [ ] **Step 4: Add result creation helper to `app/api.py`**

Insert this helper near the existing `generate` function:

```python
def _create_result_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    job_payload = dict(payload)
    quality = str(job_payload.pop("quality", "custom"))
    params_payload = job_payload.pop("params", {}) or {}
    job_payload.update(params_payload)
    if "negative_prompt" not in job_payload:
        job_payload["negative_prompt"] = ""
    if quality == "draft":
        job_payload.setdefault("num_inference_steps", 20)
        job_payload.setdefault("width", 448)
        job_payload.setdefault("height", 224)
    elif quality == "standard":
        job_payload.setdefault("num_inference_steps", 50)
        job_payload.setdefault("width", 896)
        job_payload.setdefault("height", 448)
    generated = generate(job_payload)
    result_id = result_id_for_root_job(generated["job_id"])
    result = build_result_summary(result_id, get_job_backend().list_jobs())
    if result is None:
        raise HTTPException(status_code=500, detail="Created result could not be loaded")
    return result
```

- [ ] **Step 5: Add result API endpoints to `app/api.py`**

Insert these endpoints after `generate` and before `upscale`:

```python
@app.get("/api/results")
def list_results_api() -> dict[str, Any]:
    return {"results": build_result_summaries(get_job_backend().list_jobs())}


@app.get("/api/results/{result_id}")
def get_result_api(result_id: str) -> dict[str, Any]:
    result = build_result_summary(result_id, get_job_backend().list_jobs())
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return {"result": result}


@app.post("/api/results", status_code=202)
def create_result_api(payload: dict) -> dict[str, Any]:
    return {"result": _create_result_from_payload(payload)}
```

- [ ] **Step 6: Add runtime summary endpoint to `app/api.py`**

Insert this endpoint near the existing `worker_summary` endpoint:

```python
@app.get("/api/runtime/summary")
def runtime_summary_api() -> dict[str, Any]:
    summary = _worker_summary()
    online_workers = int(summary.get("online_workers") or 0)
    busy_workers = int(summary.get("busy_workers") or 0)
    queued_jobs = int(summary.get("queued_jobs") or 0)
    running_jobs = int(summary.get("running_jobs") or 0)
    cancelling_jobs = int(summary.get("cancelling_jobs") or 0)
    total_capacity = int(summary.get("total_capacity") or 0)
    available_capacity = int(summary.get("effective_available_capacity") or 0)
    return {
        "capacity": total_capacity,
        "available_capacity": available_capacity,
        "online_workers": online_workers,
        "loading_workers": max(queued_jobs - available_capacity, 0),
        "busy_workers": busy_workers,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "cancelling_jobs": cancelling_jobs,
        "runtime_warm": online_workers > 0,
    }
```

- [ ] **Step 7: Run endpoint tests and verify pass**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_post_api_results_creates_result_view tests.test_api.ApiTests.test_get_api_results_lists_result_views tests.test_api.ApiTests.test_get_api_result_returns_404_for_missing_result tests.test_api.ApiTests.test_api_runtime_summary_uses_workbench_field_names
```

Expected: PASS.

- [ ] **Step 8: Commit result endpoints**

Run:

```bash
rtk git add app/api.py tests/test_api.py && rtk git commit -m "feat: expose result workbench api"
```

---

## Task 3: Version upscale API endpoint

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing upscale version API test**

Append this test inside `ApiTests` in `tests/test_api.py`:

```python
    def test_post_api_result_version_upscale_creates_child_version(self) -> None:
        generate = api._create_job_record(
            "job-generate-1",
            "A cinematic alpine valley at sunset",
            os.path.join(self.temp_dir.name, "outputs", "job-generate-1.mp4"),
            {"num_inference_steps": 50, "width": 896, "height": 448},
        )
        os.makedirs(os.path.dirname(generate["output_path"]), exist_ok=True)
        pathlib.Path(generate["output_path"]).write_bytes(b"video")
        api.get_job_backend().update_job(generate["job_id"], status="succeeded")

        response = self.client.post(
            "/api/results/res_job-generate-1/versions/ver_job-generate-1/upscale",
            json={
                "model": "seedvr2",
                "scale_mode": "factor",
                "scale": 4,
                "target_width": 3584,
                "target_height": 1792,
                "replace_source": False,
            },
        )

        self.assertEqual(response.status_code, 202)
        version = response.json()["version"]
        self.assertEqual(version["type"], "upscale")
        self.assertEqual(version["parent_version_id"], "ver_job-generate-1")
        self.assertEqual(version["model"], "seedvr2")
        self.assertEqual(version["scale"], 4)
        self.assertEqual(version["width"], 3584)
        self.assertEqual(version["height"], 1792)
```

Add `import pathlib` at the top of `tests/test_api.py` if it is not already present.

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_post_api_result_version_upscale_creates_child_version
```

Expected: FAIL with 404 for the new upscale route.

- [ ] **Step 3: Add version lookup helper to `app/api.py`**

Insert near `_get_job`:

```python
def _job_id_from_version_id(version_id: str) -> str:
    if not version_id.startswith("ver_"):
        raise HTTPException(status_code=404, detail="Version not found")
    return version_id.removeprefix("ver_")
```

- [ ] **Step 4: Add result version upscale endpoint to `app/api.py`**

Insert after the legacy `upscale` endpoint:

```python
@app.post("/api/results/{result_id}/versions/{version_id}/upscale", status_code=202)
def create_upscale_version_api(result_id: str, version_id: str, payload: dict) -> dict[str, Any]:
    source_job_id = _job_id_from_version_id(version_id)
    result = build_result_summary(result_id, get_job_backend().list_jobs())
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    if not any(version["job_id"] == source_job_id for version in result["versions"]):
        raise HTTPException(status_code=404, detail="Version not found")

    upscale_payload = {
        "source_job_id": source_job_id,
        "model": payload.get("model"),
        "scale_mode": payload.get("scale_mode", "factor"),
        "scale": payload.get("scale"),
        "target_width": payload.get("target_width"),
        "target_height": payload.get("target_height"),
        "replace_source": bool(payload.get("replace_source", False)),
    }
    created = upscale(upscale_payload)
    created_job_id = created["job_id"]
    version = None
    refreshed = build_result_summary(result_id, get_job_backend().list_jobs())
    if refreshed is not None:
        version = next((item for item in refreshed["versions"] if item["job_id"] == created_job_id), None)
    if version is None:
        raise HTTPException(status_code=500, detail="Created version could not be loaded")
    return {"version": version}
```

- [ ] **Step 5: Run upscale API test and verify pass**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_post_api_result_version_upscale_creates_child_version
```

Expected: PASS.

- [ ] **Step 6: Commit version upscale API**

Run:

```bash
rtk git add app/api.py tests/test_api.py && rtk git commit -m "feat: add result version upscale api"
```

---

## Task 4: Result-aware SSE events

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing event projection tests**

Append this test inside `ApiTests` in `tests/test_api.py`:

```python
    def test_collect_result_events_converts_job_updates_to_version_updates(self) -> None:
        record = api._create_job_record(
            "job-generate-1",
            "A cinematic alpine valley at sunset",
            os.path.join(self.temp_dir.name, "outputs", "job-generate-1.mp4"),
            {"num_inference_steps": 20, "width": 448, "height": 224},
        )
        known_versions = {"ver_job-generate-1": "queued"}
        api.get_job_backend().update_job(record["job_id"], status="running")

        known_versions, events = api._collect_result_store_events(known_versions)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "version_updated")
        payload = json.loads(events[0]["data"])
        self.assertEqual(payload["result_id"], "res_job-generate-1")
        self.assertEqual(payload["version_id"], "ver_job-generate-1")
        self.assertEqual(payload["job_id"], "job-generate-1")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(known_versions["ver_job-generate-1"], "running")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_collect_result_events_converts_job_updates_to_version_updates
```

Expected: FAIL with `AttributeError: module 'app.api' has no attribute '_collect_result_store_events'`.

- [ ] **Step 3: Add result event collector to `app/api.py`**

Insert near `_collect_job_store_events`:

```python
def _collect_result_store_events(known_versions: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    results = build_result_summaries(get_job_backend().list_jobs())
    next_versions: dict[str, str] = {}
    events: list[dict[str, str]] = []
    for result in results:
        for version in result["versions"]:
            version_id = str(version["version_id"])
            status = str(version["status"])
            next_versions[version_id] = status
            if known_versions.get(version_id) != status:
                events.append(
                    _sse_event(
                        "version_updated" if version_id in known_versions else "version_created",
                        {
                            "result_id": result["result_id"],
                            "version_id": version_id,
                            "job_id": version["job_id"],
                            "status": status,
                            "download_url": version.get("download_url"),
                        },
                    )
                )
    return next_versions, events
```

- [ ] **Step 4: Add `/api/events` endpoint to `app/api.py`**

Insert after `job_events`:

```python
@app.get("/api/events")
async def result_events(request: Request) -> Any:
    from sse_starlette.sse import EventSourceResponse

    async def event_generator():
        known_versions = {
            version["version_id"]: str(version["status"])
            for result in build_result_summaries(get_job_backend().list_jobs())
            for version in result["versions"]
        }
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()
        try:
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(1)
                known_versions, events = _collect_result_store_events(known_versions)
                for event in events:
                    yield event
                if not events and loop.time() - last_heartbeat >= 30:
                    last_heartbeat = loop.time()
                    yield _sse_event("heartbeat", {"ts": now_iso()})
        finally:
            return

    return EventSourceResponse(event_generator())
```

- [ ] **Step 5: Run event collector test and verify pass**

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_collect_result_events_converts_job_updates_to_version_updates
```

Expected: PASS.

- [ ] **Step 6: Commit result events**

Run:

```bash
rtk git add app/api.py tests/test_api.py && rtk git commit -m "feat: stream result workbench events"
```

---

## Task 5: React build integration and legacy static test rewrite

**Files:**
- Modify: `app/settings.py`
- Modify: `app/api.py`
- Modify: `tests/test_static_ui.py`
- Delete later: `app/static/index.html`

- [ ] **Step 1: Replace legacy static UI tests with React root tests**

Replace the full contents of `tests/test_static_ui.py` with:

```python
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api


class ReactStaticUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.frontend_dist = Path(self.temp_dir.name) / "frontend" / "dist"
        self.frontend_dist.mkdir(parents=True)
        (self.frontend_dist / "index.html").write_text(
            '<div id="root"></div><script type="module" src="/assets/index.js"></script>',
            encoding="utf-8",
        )
        patched_settings = replace(api.settings, frontend_dist_dir=str(self.frontend_dist))
        self.settings_patch = patch("app.api.settings", patched_settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.client = TestClient(api.app)

    def test_root_serves_react_build_index(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<div id="root"></div>', response.text)
        self.assertIn('/assets/index.js', response.text)

    def test_root_reports_missing_build_clearly(self) -> None:
        os.remove(self.frontend_dist / "index.html")

        response = self.client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Frontend build not found. Run npm --prefix frontend run build.")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run rewritten static UI tests and verify failure**

Run:

```bash
rtk uv run python -m unittest tests.test_static_ui
```

Expected: FAIL because `Settings` has no `frontend_dist_dir` field.

- [ ] **Step 3: Add `frontend_dist_dir` to `app/settings.py`**

Add this field to the `Settings` dataclass:

```python
    frontend_dist_dir: str
```

Add this value in `load_settings()` after `worker_store_path=worker_store_path(runtime_dir),`:

```python
        frontend_dist_dir=os.getenv(
            "FRONTEND_DIST_DIR",
            os.path.join(_HOST_ROOT, "frontend", "dist"),
        ),
```

- [ ] **Step 4: Update root route in `app/api.py`**

Replace the `root` function with:

```python
@app.get("/")
def root() -> FileResponse:
    index_path = os.path.join(settings.frontend_dist_dir, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(
            status_code=503,
            detail="Frontend build not found. Run npm --prefix frontend run build.",
        )
    return FileResponse(index_path, media_type="text/html")
```

- [ ] **Step 5: Run static UI tests and verify pass**

Run:

```bash
rtk uv run python -m unittest tests.test_static_ui
```

Expected: PASS.

- [ ] **Step 6: Commit React root integration**

Run:

```bash
rtk git add app/settings.py app/api.py tests/test_static_ui.py && rtk git commit -m "feat: serve react workbench build"
```

---

## Task 6: Scaffold Vite React TypeScript frontend

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/test/setup.ts`

- [ ] **Step 1: Create `frontend/package.json`**

Create `frontend/package.json`:

```json
{
  "name": "panowan-result-workbench",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 0.0.0.0",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "type-check": "tsc --noEmit"
  },
  "dependencies": {
    "@react-three/fiber": "^8.16.8",
    "@vitejs/plugin-react": "^4.3.1",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.166.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@types/three": "^0.166.0",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^5.3.4",
    "vitest": "^2.1.9"
  }
}
```

- [ ] **Step 2: Create TypeScript and Vite config files**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": []
}
```

Create `frontend/vite.config.ts`:

```ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
```

Create `frontend/vitest.config.ts`:

```ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
```

- [ ] **Step 3: Create initial React entry files**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PanoWan 视频生成</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/src/main.tsx`:

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/tokens.css'
import './styles/app.css'

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

Create `frontend/src/App.tsx`:

```tsx
export default function App() {
  return <div className="app-shell">PanoWan 视频生成</div>
}
```

Create `frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 4: Create initial CSS files**

Create `frontend/src/styles/tokens.css`:

```css
:root {
  color-scheme: light;
  --color-bg: #ffffff;
  --color-surface: #ffffff;
  --color-surface-muted: #f7f7f7;
  --color-text: #242424;
  --color-muted: #898989;
  --color-ring: rgba(34, 42, 53, 0.08);
  --color-success: #15803d;
  --color-error: #b91c1c;
  --shadow-card: rgba(19, 19, 22, 0.7) 0 1px 5px -4px, rgba(34, 42, 53, 0.08) 0 0 0 1px, rgba(34, 42, 53, 0.05) 0 4px 8px 0;
  --radius-card: 12px;
  --radius-pill: 9999px;
  font-family: Inter, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
}
```

Create `frontend/src/styles/app.css`:

```css
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  background: var(--color-bg);
  color: var(--color-text);
}

button,
input,
textarea,
select {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  padding: 24px;
}
```

- [ ] **Step 5: Install frontend dependencies**

Run:

```bash
rtk npm --prefix frontend install
```

Expected: install succeeds and creates `frontend/package-lock.json`.

- [ ] **Step 6: Build frontend and verify pass**

Run:

```bash
rtk npm --prefix frontend run build
```

Expected: PASS and `frontend/dist/index.html` exists.

- [ ] **Step 7: Commit frontend scaffold**

Run:

```bash
rtk git add frontend && rtk git commit -m "feat: scaffold react workbench"
```

---

## Task 7: Frontend API types and clients

**Files:**
- Create: `frontend/src/types/result.ts`
- Create: `frontend/src/types/runtime.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/resultClient.ts`
- Create: `frontend/src/api/runtimeClient.ts`
- Create: `frontend/src/api/eventClient.ts`
- Test: `frontend/src/api/resultClient.test.ts`

- [ ] **Step 1: Add API client tests**

Create `frontend/src/api/resultClient.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { createResult, fetchResults } from './resultClient'

describe('resultClient', () => {
  it('fetches result summaries', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ results: [{ result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'completed', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:01:00Z', versions: [] }] }), { status: 200 })))

    const results = await fetchResults()

    expect(results[0].result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results')
  })

  it('creates a result with workbench payload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ result: { result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'Prompt', status: 'queued', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:00:00Z', versions: [] } }), { status: 202 })))

    const result = await createResult({ prompt: 'Prompt', negative_prompt: '', quality: 'draft', params: { num_inference_steps: 20, width: 448, height: 224, seed: 0 } })

    expect(result.result_id).toBe('res_job_1')
    expect(fetch).toHaveBeenCalledWith('/api/results', expect.objectContaining({ method: 'POST' }))
  })
})
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/api/resultClient.test.ts
```

Expected: FAIL because `resultClient.ts` does not exist.

- [ ] **Step 3: Create frontend types**

Create `frontend/src/types/result.ts`:

```ts
export type JobStatus = 'queued' | 'claimed' | 'running' | 'cancelling' | 'succeeded' | 'completed' | 'failed' | 'cancelled'
export type ResultStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'mixed'
export type ResultVersionType = 'original' | 'upscale'
export type ComparisonMode = 'side-by-side' | 'single' | 'slider' | 'ab'

export interface ResultVersion {
  version_id: string
  job_id: string
  parent_version_id?: string | null
  type: ResultVersionType
  label: string
  status: JobStatus
  model?: string | null
  scale?: number | null
  width?: number | null
  height?: number | null
  duration_seconds?: number | null
  fps?: number | null
  bitrate_mbps?: number | null
  file_size_bytes?: number | null
  thumbnail_url?: string | null
  preview_url?: string | null
  download_url?: string | null
  params: Record<string, unknown>
  error?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface ResultSummary {
  result_id: string
  root_job_id: string
  prompt: string
  negative_prompt?: string
  status: ResultStatus
  selected_version_id?: string | null
  created_at?: string | null
  updated_at?: string | null
  versions: ResultVersion[]
}

export interface CreateResultPayload {
  prompt: string
  negative_prompt: string
  quality: 'draft' | 'standard' | 'custom'
  params: {
    num_inference_steps: number
    width: number
    height: number
    seed: number
  }
}

export interface CreateUpscalePayload {
  model: string
  scale_mode: 'factor' | 'resolution'
  scale?: number
  target_width?: number
  target_height?: number
  replace_source: boolean
}
```

Create `frontend/src/types/runtime.ts`:

```ts
export interface RuntimeSummary {
  capacity: number
  available_capacity: number
  online_workers: number
  loading_workers: number
  busy_workers: number
  queued_jobs: number
  running_jobs: number
  cancelling_jobs: number
  runtime_warm: boolean
}
```

- [ ] **Step 4: Create API clients**

Create `frontend/src/api/client.ts`:

```ts
export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(String(body.detail ?? response.statusText))
  }
  return response.json() as Promise<T>
}
```

Create `frontend/src/api/resultClient.ts`:

```ts
import { requestJson } from './client'
import type { CreateResultPayload, CreateUpscalePayload, ResultSummary, ResultVersion } from '../types/result'

export async function fetchResults(): Promise<ResultSummary[]> {
  const body = await requestJson<{ results: ResultSummary[] }>('/api/results')
  return body.results
}

export async function fetchResult(resultId: string): Promise<ResultSummary> {
  const body = await requestJson<{ result: ResultSummary }>(`/api/results/${resultId}`)
  return body.result
}

export async function createResult(payload: CreateResultPayload): Promise<ResultSummary> {
  const body = await requestJson<{ result: ResultSummary }>('/api/results', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return body.result
}

export async function createUpscaleVersion(resultId: string, versionId: string, payload: CreateUpscalePayload): Promise<ResultVersion> {
  const body = await requestJson<{ version: ResultVersion }>(`/api/results/${resultId}/versions/${versionId}/upscale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return body.version
}
```

Create `frontend/src/api/runtimeClient.ts`:

```ts
import { requestJson } from './client'
import type { RuntimeSummary } from '../types/runtime'

export function fetchRuntimeSummary(): Promise<RuntimeSummary> {
  return requestJson<RuntimeSummary>('/api/runtime/summary')
}
```

Create `frontend/src/api/eventClient.ts`:

```ts
export type WorkbenchEventHandler = (eventName: string, payload: unknown) => void

export function connectWorkbenchEvents(handler: WorkbenchEventHandler): EventSource {
  const source = new EventSource('/api/events')
  for (const name of ['result_created', 'result_updated', 'version_created', 'version_updated', 'version_deleted', 'runtime_updated', 'heartbeat']) {
    source.addEventListener(name, (event) => {
      handler(name, JSON.parse((event as MessageEvent).data))
    })
  }
  return source
}
```

- [ ] **Step 5: Run API client tests and verify pass**

Run:

```bash
rtk npm --prefix frontend run test -- src/api/resultClient.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit API clients**

Run:

```bash
rtk git add frontend/src/types frontend/src/api && rtk git commit -m "feat: add workbench api clients"
```

---

## Task 8: Frontend stores and workbench state

**Files:**
- Create: `frontend/src/stores/resultStore.ts`
- Create: `frontend/src/stores/runtimeStore.ts`
- Create: `frontend/src/stores/workspaceStore.ts`
- Test: `frontend/src/stores/resultStore.test.ts`

- [ ] **Step 1: Add store tests**

Create `frontend/src/stores/resultStore.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { applyVersionUpdate, selectInitialVersion } from './resultStore'
import type { ResultSummary } from '../types/result'

const result: ResultSummary = {
  result_id: 'res_job_1',
  root_job_id: 'job_1',
  prompt: 'Prompt',
  status: 'completed',
  selected_version_id: 'ver_job_1',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:01:00Z',
  versions: [{ version_id: 'ver_job_1', job_id: 'job_1', type: 'original', label: '原始生成', status: 'succeeded', params: {} }],
}

describe('resultStore helpers', () => {
  it('selects backend selected version when present', () => {
    expect(selectInitialVersion(result)).toBe('ver_job_1')
  })

  it('applies version status updates without changing other versions', () => {
    const updated = applyVersionUpdate(result, { version_id: 'ver_job_1', status: 'running' })

    expect(updated.versions[0].status).toBe('running')
    expect(updated.result_id).toBe('res_job_1')
  })
})
```

- [ ] **Step 2: Run store tests and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/stores/resultStore.test.ts
```

Expected: FAIL because `resultStore.ts` does not exist.

- [ ] **Step 3: Create store helpers**

Create `frontend/src/stores/resultStore.ts`:

```ts
import type { ResultSummary, ResultVersion } from '../types/result'

export interface VersionUpdatePayload {
  version_id: string
  status?: ResultVersion['status']
  download_url?: string | null
  preview_url?: string | null
  error?: string | null
}

export function selectInitialVersion(result: ResultSummary): string | null {
  if (result.selected_version_id) return result.selected_version_id
  return result.versions.at(-1)?.version_id ?? null
}

export function applyVersionUpdate(result: ResultSummary, patch: VersionUpdatePayload): ResultSummary {
  return {
    ...result,
    versions: result.versions.map((version) =>
      version.version_id === patch.version_id
        ? {
            ...version,
            status: patch.status ?? version.status,
            download_url: patch.download_url ?? version.download_url,
            preview_url: patch.preview_url ?? version.preview_url,
            error: patch.error ?? version.error,
          }
        : version,
    ),
  }
}

export function upsertResult(results: ResultSummary[], next: ResultSummary): ResultSummary[] {
  const index = results.findIndex((result) => result.result_id === next.result_id)
  if (index === -1) return [next, ...results]
  return results.map((result) => (result.result_id === next.result_id ? next : result))
}
```

Create `frontend/src/stores/runtimeStore.ts`:

```ts
import type { RuntimeSummary } from '../types/runtime'

export const emptyRuntimeSummary: RuntimeSummary = {
  capacity: 0,
  available_capacity: 0,
  online_workers: 0,
  loading_workers: 0,
  busy_workers: 0,
  queued_jobs: 0,
  running_jobs: 0,
  cancelling_jobs: 0,
  runtime_warm: false,
}
```

Create `frontend/src/stores/workspaceStore.ts`:

```ts
import type { ComparisonMode } from '../types/result'

export interface PanoViewState {
  yaw: number
  pitch: number
  fov: number
}

export interface WorkspaceState {
  selectedResultId: string | null
  selectedVersionId: string | null
  comparisonMode: ComparisonMode
  viewState: PanoViewState
  currentTime: number
  paused: boolean
  muted: boolean
}

export const initialWorkspaceState: WorkspaceState = {
  selectedResultId: null,
  selectedVersionId: null,
  comparisonMode: 'side-by-side',
  viewState: { yaw: 0, pitch: 0, fov: 90 },
  currentTime: 0,
  paused: true,
  muted: false,
}
```

- [ ] **Step 4: Run store tests and verify pass**

Run:

```bash
rtk npm --prefix frontend run test -- src/stores/resultStore.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit stores**

Run:

```bash
rtk git add frontend/src/stores && rtk git commit -m "feat: add workbench state helpers"
```

---

## Task 9: App shell, status bar, and desktop layout

**Files:**
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/RuntimeStatusBar.tsx`
- Create: `frontend/src/components/StatusPill.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles/app.css`
- Test: `frontend/src/components/AppShell.test.tsx`

- [ ] **Step 1: Add shell render test**

Create `frontend/src/components/AppShell.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import AppShell from './AppShell'
import { emptyRuntimeSummary } from '../stores/runtimeStore'

describe('AppShell', () => {
  it('renders the five workbench regions', () => {
    render(<AppShell runtime={emptyRuntimeSummary} />)

    expect(screen.getByText('PanoWan 视频生成')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '新建任务' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '结果预览' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '版本与超分' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近任务' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run shell test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/components/AppShell.test.tsx
```

Expected: FAIL because `AppShell.tsx` does not exist.

- [ ] **Step 3: Create shell components**

Create `frontend/src/components/StatusPill.tsx`:

```tsx
interface StatusPillProps {
  label: string
  value: string | number
  active?: boolean
}

export default function StatusPill({ label, value, active = false }: StatusPillProps) {
  return (
    <span className="status-pill">
      {active ? <span className="status-dot" /> : null}
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  )
}
```

Create `frontend/src/components/RuntimeStatusBar.tsx`:

```tsx
import type { RuntimeSummary } from '../types/runtime'
import StatusPill from './StatusPill'

interface RuntimeStatusBarProps {
  runtime: RuntimeSummary
}

export default function RuntimeStatusBar({ runtime }: RuntimeStatusBarProps) {
  return (
    <div className="runtime-status-bar" aria-label="运行状态">
      <StatusPill label="容量" value={runtime.available_capacity} />
      <StatusPill label="Worker" value={runtime.online_workers > 0 ? '闲置' : '离线'} active={runtime.online_workers > 0} />
      <StatusPill label="队列" value={runtime.queued_jobs} />
      <StatusPill label="Runtime" value={runtime.runtime_warm ? 'Warm' : 'Cold'} active={runtime.runtime_warm} />
      <StatusPill label="自动刷新" value="中" active />
      <button className="icon-button" type="button" aria-label="设置">⚙</button>
    </div>
  )
}
```

Create `frontend/src/components/AppShell.tsx`:

```tsx
import type { RuntimeSummary } from '../types/runtime'
import RuntimeStatusBar from './RuntimeStatusBar'

interface AppShellProps {
  runtime: RuntimeSummary
}

export default function AppShell({ runtime }: AppShellProps) {
  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <h1>PanoWan 视频生成</h1>
        <RuntimeStatusBar runtime={runtime} />
      </header>
      <section className="workbench-grid" aria-label="PanoWan 结果工作台">
        <aside className="workbench-card create-region" aria-label="新建任务">新建任务</aside>
        <section className="workbench-card preview-region" aria-label="结果预览">结果预览</section>
        <aside className="workbench-card versions-region" aria-label="版本与超分">版本与超分</aside>
      </section>
      <section className="workbench-card recent-region" aria-label="最近任务">最近任务</section>
    </main>
  )
}
```

Modify `frontend/src/App.tsx`:

```tsx
import AppShell from './components/AppShell'
import { emptyRuntimeSummary } from './stores/runtimeStore'

export default function App() {
  return <AppShell runtime={emptyRuntimeSummary} />
}
```

- [ ] **Step 4: Add shell CSS**

Append to `frontend/src/styles/app.css`:

```css
.workbench-shell {
  min-height: 100vh;
  padding: 24px;
  display: grid;
  gap: 20px;
  background: var(--color-bg);
}

.workbench-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.workbench-header h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1;
  color: var(--color-text);
}

.runtime-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.status-pill,
.icon-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 36px;
  padding: 0 13px;
  border: 0;
  border-radius: var(--radius-pill);
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: var(--shadow-card);
  font-weight: 600;
}

.status-pill strong {
  font-weight: 700;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-success);
}

.icon-button {
  width: 36px;
  justify-content: center;
  cursor: pointer;
}

.workbench-grid {
  display: grid;
  grid-template-columns: minmax(260px, 300px) minmax(520px, 1fr) minmax(280px, 320px);
  gap: 16px;
  align-items: stretch;
}

.workbench-card {
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  border-radius: var(--radius-card);
}

.create-region,
.preview-region,
.versions-region,
.recent-region {
  padding: 16px;
}

.preview-region {
  min-height: 520px;
}

.recent-region {
  min-height: 180px;
}

@media (max-width: 1024px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run shell test and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/components/AppShell.test.tsx && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit shell layout**

Run:

```bash
rtk git add frontend/src && rtk git commit -m "feat: add result workbench shell"
```

---

## Task 10: Create task panel

**Files:**
- Create: `frontend/src/features/create/CreateTaskPanel.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Test: `frontend/src/features/create/CreateTaskPanel.test.tsx`

- [ ] **Step 1: Add create panel test**

Create `frontend/src/features/create/CreateTaskPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CreateTaskPanel from './CreateTaskPanel'

describe('CreateTaskPanel', () => {
  it('submits draft result payload', async () => {
    const onSubmit = vi.fn()
    render(<CreateTaskPanel onSubmit={onSubmit} />)

    await userEvent.clear(screen.getByLabelText('Prompt'))
    await userEvent.type(screen.getByLabelText('Prompt'), 'A cinematic alpine valley at sunset')
    await userEvent.click(screen.getByRole('button', { name: '草稿' }))
    await userEvent.click(screen.getByRole('button', { name: '提交任务' }))

    expect(onSubmit).toHaveBeenCalledWith({
      prompt: 'A cinematic alpine valley at sunset',
      negative_prompt: '',
      quality: 'draft',
      params: { num_inference_steps: 20, width: 448, height: 224, seed: 0 },
    })
  })
})
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/create/CreateTaskPanel.test.tsx
```

Expected: FAIL because component does not exist.

- [ ] **Step 3: Create `CreateTaskPanel.tsx`**

Create `frontend/src/features/create/CreateTaskPanel.tsx`:

```tsx
import { useState } from 'react'
import type { CreateResultPayload } from '../../types/result'

interface CreateTaskPanelProps {
  onSubmit: (payload: CreateResultPayload) => void | Promise<void>
}

type Quality = 'draft' | 'standard' | 'custom'

const presets = {
  draft: { num_inference_steps: 20, width: 448, height: 224 },
  standard: { num_inference_steps: 50, width: 896, height: 448 },
}

export default function CreateTaskPanel({ onSubmit }: CreateTaskPanelProps) {
  const [prompt, setPrompt] = useState('A cinematic alpine valley at sunset with drifting clouds and wide panoramic motion.')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [quality, setQuality] = useState<Quality>('standard')
  const [seed, setSeed] = useState(0)
  const selected = quality === 'draft' ? presets.draft : presets.standard

  return (
    <form
      className="create-task-panel"
      onSubmit={(event) => {
        event.preventDefault()
        void onSubmit({
          prompt,
          negative_prompt: negativePrompt,
          quality,
          params: {
            num_inference_steps: selected.num_inference_steps,
            width: selected.width,
            height: selected.height,
            seed,
          },
        })
      }}
    >
      <h2>新建任务</h2>
      <label>
        Prompt
        <span className="char-count">{prompt.length}/1000</span>
        <textarea value={prompt} maxLength={1000} onChange={(event) => setPrompt(event.target.value)} />
      </label>
      <div className="quality-group" aria-label="质量预设">
        <button type="button" className={quality === 'draft' ? 'segmented active' : 'segmented'} onClick={() => setQuality('draft')}>草稿</button>
        <button type="button" className={quality === 'standard' ? 'segmented active' : 'segmented'} onClick={() => setQuality('standard')}>标准</button>
        <button type="button" className={quality === 'custom' ? 'segmented active' : 'segmented'} onClick={() => setQuality('custom')}>自定义</button>
      </div>
      <p className="preset-summary">{selected.num_inference_steps} 步 · {selected.width}×{selected.height}</p>
      <label>
        负向提示词（可选）
        <textarea value={negativePrompt} maxLength={500} placeholder="例如：overexposed, static, blurry" onChange={(event) => setNegativePrompt(event.target.value)} />
      </label>
      <label>
        随机种子（可选）
        <input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} />
      </label>
      <button className="primary-action" type="submit">提交任务</button>
      <p className="estimate">预计耗时：约 1 分钟 40 秒</p>
    </form>
  )
}
```

- [ ] **Step 4: Wire create panel into shell**

Modify `frontend/src/components/AppShell.tsx` to import and render `CreateTaskPanel`:

```tsx
import type { RuntimeSummary } from '../types/runtime'
import CreateTaskPanel from '../features/create/CreateTaskPanel'
import RuntimeStatusBar from './RuntimeStatusBar'

interface AppShellProps {
  runtime: RuntimeSummary
}

export default function AppShell({ runtime }: AppShellProps) {
  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <h1>PanoWan 视频生成</h1>
        <RuntimeStatusBar runtime={runtime} />
      </header>
      <section className="workbench-grid" aria-label="PanoWan 结果工作台">
        <aside className="workbench-card create-region" aria-label="新建任务">
          <CreateTaskPanel onSubmit={() => undefined} />
        </aside>
        <section className="workbench-card preview-region" aria-label="结果预览">结果预览</section>
        <aside className="workbench-card versions-region" aria-label="版本与超分">版本与超分</aside>
      </section>
      <section className="workbench-card recent-region" aria-label="最近任务">最近任务</section>
    </main>
  )
}
```

- [ ] **Step 5: Add create panel CSS**

Append to `frontend/src/styles/app.css`:

```css
.create-task-panel {
  display: grid;
  gap: 16px;
}

.create-task-panel h2 {
  margin: 0;
  font-size: 16px;
}

.create-task-panel label {
  display: grid;
  gap: 8px;
  color: var(--color-text);
  font-weight: 600;
}

.char-count {
  float: right;
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 500;
}

.create-task-panel textarea,
.create-task-panel input {
  width: 100%;
  border: 0;
  border-radius: 8px;
  box-shadow: rgba(34, 42, 53, 0.12) 0 0 0 1px;
  padding: 10px 12px;
  color: var(--color-text);
  background: var(--color-surface);
}

.create-task-panel textarea {
  min-height: 96px;
  resize: vertical;
}

.quality-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  padding: 3px;
  border-radius: 10px;
  background: var(--color-surface-muted);
  box-shadow: rgba(34, 42, 53, 0.08) 0 0 0 1px;
}

.segmented {
  border: 0;
  border-radius: 8px;
  padding: 9px;
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
}

.segmented.active {
  background: #242424;
  color: white;
}

.preset-summary,
.estimate {
  margin: 0;
  color: var(--color-muted);
  font-size: 13px;
}

.primary-action {
  border: 0;
  border-radius: 8px;
  padding: 12px 16px;
  background: #242424;
  color: #ffffff;
  font-weight: 700;
  cursor: pointer;
}
```

- [ ] **Step 6: Run create panel tests and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/create/CreateTaskPanel.test.tsx src/components/AppShell.test.tsx && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 7: Commit create panel**

Run:

```bash
rtk git add frontend/src && rtk git commit -m "feat: add create task panel"
```

---

## Task 11: Result workspace, versions panel, and recent tasks UI

**Files:**
- Create: `frontend/src/features/results/ResultPreviewWorkspace.tsx`
- Create: `frontend/src/features/results/VersionStrip.tsx`
- Create: `frontend/src/features/results/ResultMetadataBar.tsx`
- Create: `frontend/src/features/versions/VersionUpscalePanel.tsx`
- Create: `frontend/src/features/versions/UpscaleForm.tsx`
- Create: `frontend/src/features/tasks/RecentTasksTable.tsx`
- Create: `frontend/src/features/tasks/TaskActionsMenu.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Test: `frontend/src/features/results/ResultPreviewWorkspace.test.tsx`

- [ ] **Step 1: Add result workspace test**

Create `frontend/src/features/results/ResultPreviewWorkspace.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ResultPreviewWorkspace from './ResultPreviewWorkspace'
import type { ResultSummary } from '../../types/result'

const result: ResultSummary = {
  result_id: 'res_job_1',
  root_job_id: 'job_1',
  prompt: 'A cinematic alpine valley at sunset',
  status: 'completed',
  selected_version_id: 'ver_original',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:01:00Z',
  versions: [
    { version_id: 'ver_original', job_id: 'job_1', type: 'original', label: '原始生成', status: 'succeeded', width: 896, height: 448, params: {}, download_url: '/api/jobs/job_1/download' },
    { version_id: 'ver_4x', job_id: 'job_2', parent_version_id: 'ver_original', type: 'upscale', label: '4x SeedVR2', status: 'succeeded', width: 3584, height: 1792, model: 'seedvr2', scale: 4, params: {}, download_url: '/api/jobs/job_2/download' },
  ],
}

describe('ResultPreviewWorkspace', () => {
  it('renders comparison modes and version metadata', () => {
    render(<ResultPreviewWorkspace result={result} selectedVersionId="ver_4x" />)

    expect(screen.getByText('结果预览')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '左右对比' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '单看' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '滑块对比' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'A/B 对比' })).toBeInTheDocument()
    expect(screen.getByText('4x SeedVR2')).toBeInTheDocument()
    expect(screen.getByText('3584×1792')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/results/ResultPreviewWorkspace.test.tsx
```

Expected: FAIL because components do not exist.

- [ ] **Step 3: Create result workspace components**

Create `frontend/src/features/results/VersionStrip.tsx`:

```tsx
import type { ResultVersion } from '../../types/result'

interface VersionStripProps {
  versions: ResultVersion[]
  selectedVersionId: string | null
}

export default function VersionStrip({ versions, selectedVersionId }: VersionStripProps) {
  return (
    <div className="version-strip" aria-label="版本切换">
      {versions.map((version) => (
        <button key={version.version_id} className={version.version_id === selectedVersionId ? 'version-card active' : 'version-card'} type="button">
          <strong>{version.label}</strong>
          <span>{version.width && version.height ? `${version.width}×${version.height}` : '处理中'}</span>
        </button>
      ))}
      <button className="version-card ghost" type="button">+ 新建超分版本</button>
    </div>
  )
}
```

Create `frontend/src/features/results/ResultMetadataBar.tsx`:

```tsx
import type { ResultVersion } from '../../types/result'

interface ResultMetadataBarProps {
  version: ResultVersion | null
}

export default function ResultMetadataBar({ version }: ResultMetadataBarProps) {
  return (
    <dl className="metadata-bar">
      <div><dt>模型</dt><dd>{version?.model ?? (version?.type === 'original' ? 'PanoWan T2V' : '—')}</dd></div>
      <div><dt>分辨率</dt><dd>{version?.width && version.height ? `${version.width}×${version.height}` : '—'}</dd></div>
      <div><dt>时长</dt><dd>{version?.duration_seconds ? `${version.duration_seconds}s` : '—'}</dd></div>
      <div><dt>帧率</dt><dd>{version?.fps ? `${version.fps}fps` : '—'}</dd></div>
      <div><dt>码率</dt><dd>{version?.bitrate_mbps ? `${version.bitrate_mbps} Mbps` : '—'}</dd></div>
      <div><dt>大小</dt><dd>{version?.file_size_bytes ? `${Math.round(version.file_size_bytes / 1024 / 1024)} MB` : '—'}</dd></div>
    </dl>
  )
}
```

Create `frontend/src/features/results/ResultPreviewWorkspace.tsx`:

```tsx
import type { ResultSummary } from '../../types/result'
import ResultMetadataBar from './ResultMetadataBar'
import VersionStrip from './VersionStrip'

interface ResultPreviewWorkspaceProps {
  result: ResultSummary | null
  selectedVersionId: string | null
}

export default function ResultPreviewWorkspace({ result, selectedVersionId }: ResultPreviewWorkspaceProps) {
  const selected = result?.versions.find((version) => version.version_id === selectedVersionId) ?? result?.versions[0] ?? null
  if (!result) {
    return <div className="result-workspace empty">提交或选择一个任务后查看结果。</div>
  }
  return (
    <div className="result-workspace">
      <header className="result-workspace-header">
        <div>
          <h2>结果预览 <span className="status-inline">● {result.status}</span></h2>
          <p>任务来源：{result.root_job_id}</p>
        </div>
        <div className="compare-tabs" aria-label="对比模式">
          <button type="button">左右对比</button>
          <button type="button">单看</button>
          <button type="button">滑块对比</button>
          <button type="button">A/B 对比</button>
        </div>
      </header>
      <div className="viewer-placeholder">360° 全景预览</div>
      <VersionStrip versions={result.versions} selectedVersionId={selected?.version_id ?? null} />
      <ResultMetadataBar version={selected} />
    </div>
  )
}
```

- [ ] **Step 4: Create versions and tasks supporting components**

Create `frontend/src/features/versions/UpscaleForm.tsx`:

```tsx
export default function UpscaleForm() {
  return (
    <form className="upscale-form">
      <h3>新建超分任务</h3>
      <label>模型<select><option>SeedVR2 4x (SOTA)</option><option>Real-ESRGAN 2x</option></select></label>
      <div className="quality-group"><button className="segmented active" type="button">2x</button><button className="segmented" type="button">4x</button><button className="segmented" type="button">自定义分辨率</button></div>
      <button className="primary-action" type="button">开始超分</button>
    </form>
  )
}
```

Create `frontend/src/features/versions/VersionUpscalePanel.tsx`:

```tsx
import type { ResultSummary } from '../../types/result'
import UpscaleForm from './UpscaleForm'

interface VersionUpscalePanelProps {
  result: ResultSummary | null
}

export default function VersionUpscalePanel({ result }: VersionUpscalePanelProps) {
  return (
    <div className="version-upscale-panel">
      <h2>版本与超分</h2>
      <div className="version-timeline">
        {result?.versions.map((version) => (
          <article key={version.version_id} className="timeline-item">
            <strong>{version.label}</strong>
            <span>{version.status}</span>
          </article>
        )) ?? <p>暂无版本</p>}
      </div>
      <UpscaleForm />
    </div>
  )
}
```

Create `frontend/src/features/tasks/TaskActionsMenu.tsx`:

```tsx
export default function TaskActionsMenu() {
  return <button className="icon-button" type="button" aria-label="更多操作">⋯</button>
}
```

Create `frontend/src/features/tasks/RecentTasksTable.tsx`:

```tsx
import type { ResultSummary } from '../../types/result'
import TaskActionsMenu from './TaskActionsMenu'

interface RecentTasksTableProps {
  results: ResultSummary[]
}

export default function RecentTasksTable({ results }: RecentTasksTableProps) {
  return (
    <div className="recent-tasks-table">
      <header><h2>最近任务 <span>{results.length}</span></h2></header>
      <table>
        <thead><tr><th>缩略图</th><th>状态</th><th>Prompt</th><th>版本</th><th>操作</th></tr></thead>
        <tbody>
          {results.map((result) => (
            <tr key={result.result_id}>
              <td><div className="thumbnail-cell" /></td>
              <td>{result.status}</td>
              <td>{result.prompt}</td>
              <td>{result.versions.map((version) => version.label).join(' / ')}</td>
              <td><TaskActionsMenu /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 5: Wire components into shell with sample data**

Modify `frontend/src/components/AppShell.tsx`:

```tsx
import type { RuntimeSummary } from '../types/runtime'
import type { ResultSummary } from '../types/result'
import CreateTaskPanel from '../features/create/CreateTaskPanel'
import ResultPreviewWorkspace from '../features/results/ResultPreviewWorkspace'
import RecentTasksTable from '../features/tasks/RecentTasksTable'
import VersionUpscalePanel from '../features/versions/VersionUpscalePanel'
import RuntimeStatusBar from './RuntimeStatusBar'

interface AppShellProps {
  runtime: RuntimeSummary
}

const sampleResult: ResultSummary = {
  result_id: 'res_sample',
  root_job_id: 'job_sample',
  prompt: 'A cinematic alpine valley at sunset with drifting clouds',
  status: 'completed',
  selected_version_id: 'ver_4x',
  created_at: '2026-05-02T12:00:00Z',
  updated_at: '2026-05-02T12:03:00Z',
  versions: [
    { version_id: 'ver_original', job_id: 'job_sample', type: 'original', label: '原始生成', status: 'succeeded', width: 896, height: 448, params: {} },
    { version_id: 'ver_4x', job_id: 'job_upscale', parent_version_id: 'ver_original', type: 'upscale', label: '4x SeedVR2', status: 'succeeded', width: 3584, height: 1792, model: 'SeedVR2 4x', scale: 4, params: {} },
  ],
}

export default function AppShell({ runtime }: AppShellProps) {
  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <h1>PanoWan 视频生成</h1>
        <RuntimeStatusBar runtime={runtime} />
      </header>
      <section className="workbench-grid" aria-label="PanoWan 结果工作台">
        <aside className="workbench-card create-region" aria-label="新建任务"><CreateTaskPanel onSubmit={() => undefined} /></aside>
        <section className="workbench-card preview-region" aria-label="结果预览"><ResultPreviewWorkspace result={sampleResult} selectedVersionId="ver_4x" /></section>
        <aside className="workbench-card versions-region" aria-label="版本与超分"><VersionUpscalePanel result={sampleResult} /></aside>
      </section>
      <section className="workbench-card recent-region" aria-label="最近任务"><RecentTasksTable results={[sampleResult]} /></section>
    </main>
  )
}
```

- [ ] **Step 6: Add workspace CSS**

Append to `frontend/src/styles/app.css`:

```css
.result-workspace {
  display: grid;
  gap: 16px;
  height: 100%;
}

.result-workspace.empty {
  min-height: 460px;
  place-items: center;
  color: var(--color-muted);
  text-align: center;
}

.result-workspace-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.result-workspace-header h2,
.version-upscale-panel h2,
.recent-tasks-table h2 {
  margin: 0;
  font-size: 16px;
}

.result-workspace-header p {
  margin: 6px 0 0;
  color: var(--color-muted);
  font-size: 13px;
}

.status-inline {
  color: var(--color-success);
  font-size: 12px;
  font-weight: 600;
}

.compare-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.compare-tabs button,
.viewer-controls button,
.compare-inline-controls button {
  border: 0;
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: rgba(34, 42, 53, 0.12) 0 0 0 1px;
  padding: 8px 10px;
  cursor: pointer;
}

.compare-tabs button.active,
.compare-inline-controls button.active {
  background: #242424;
  color: #ffffff;
}

.viewer-placeholder,
.viewer-stage {
  min-height: 360px;
  overflow: hidden;
  border-radius: 12px;
  background: #111111;
  color: #ffffff;
}

.viewer-placeholder {
  display: grid;
  place-items: center;
}

.version-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 10px;
}

.version-card {
  display: grid;
  gap: 4px;
  border: 0;
  border-radius: 10px;
  padding: 12px;
  text-align: left;
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: rgba(34, 42, 53, 0.12) 0 0 0 1px;
  cursor: pointer;
}

.version-card span {
  color: var(--color-muted);
  font-size: 12px;
}

.version-card.active {
  box-shadow: rgba(36, 36, 36, 0.9) 0 0 0 1px, rgba(34, 42, 53, 0.08) 0 8px 20px;
}

.version-card.ghost {
  color: var(--color-muted);
  place-content: center;
  text-align: center;
}

.metadata-bar {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.metadata-bar div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border-radius: 10px;
  background: var(--color-surface-muted);
}

.metadata-bar dt {
  color: var(--color-muted);
  font-size: 12px;
}

.metadata-bar dd {
  margin: 0;
  color: var(--color-text);
  font-weight: 700;
}

.version-upscale-panel,
.upscale-form {
  display: grid;
  gap: 14px;
}

.version-timeline {
  display: grid;
  gap: 10px;
}

.timeline-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border-radius: 10px;
  background: var(--color-surface-muted);
}

.timeline-item span {
  color: var(--color-muted);
  font-size: 12px;
}

.upscale-form label {
  display: grid;
  gap: 8px;
  font-weight: 600;
}

.upscale-form select {
  border: 0;
  border-radius: 8px;
  box-shadow: rgba(34, 42, 53, 0.12) 0 0 0 1px;
  padding: 10px 12px;
  background: var(--color-surface);
}

.recent-tasks-table {
  overflow-x: auto;
}

.recent-tasks-table header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.recent-tasks-table table {
  width: 100%;
  border-collapse: collapse;
}

.recent-tasks-table th,
.recent-tasks-table td {
  padding: 12px 10px;
  text-align: left;
  border-bottom: 1px solid #eeeeee;
}

.recent-tasks-table th {
  color: var(--color-muted);
  font-size: 12px;
  font-weight: 600;
}

.thumbnail-cell {
  width: 56px;
  height: 32px;
  border-radius: 8px;
  background: var(--color-surface-muted);
  box-shadow: rgba(34, 42, 53, 0.12) 0 0 0 1px inset;
}
```

- [ ] **Step 7: Run workspace tests and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/results/ResultPreviewWorkspace.test.tsx src/components/AppShell.test.tsx && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 8: Commit workbench UI structure**

Run:

```bash
rtk git add frontend/src && rtk git commit -m "feat: add result workbench panels"
```

---

## Task 12: Panorama viewer component

**Files:**
- Create: `frontend/src/features/viewer/PanoVideoViewer.tsx`
- Create: `frontend/src/features/viewer/ViewerControls.tsx`
- Test: `frontend/src/features/viewer/PanoVideoViewer.test.tsx`

- [ ] **Step 1: Add viewer smoke test**

Create `frontend/src/features/viewer/PanoVideoViewer.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PanoVideoViewer from './PanoVideoViewer'

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: { children: React.ReactNode }) => <div data-testid="canvas">{children}</div>,
  useThree: () => ({ camera: { position: { set: vi.fn() }, rotation: { order: 'XYZ', x: 0, y: 0 } }, gl: { domElement: document.createElement('canvas') } }),
}))

describe('PanoVideoViewer', () => {
  it('renders a 360 viewer canvas', () => {
    render(<PanoVideoViewer src="/api/jobs/job_1/download" paused currentTime={0} muted viewState={{ yaw: 0, pitch: 0, fov: 90 }} onTimeChange={() => undefined} onDurationChange={() => undefined} onViewChange={() => undefined} onError={() => undefined} />)

    expect(screen.getByTestId('canvas')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run viewer test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/viewer/PanoVideoViewer.test.tsx
```

Expected: FAIL because viewer component does not exist.

- [ ] **Step 3: Create `PanoVideoViewer.tsx`**

Create `frontend/src/features/viewer/PanoVideoViewer.tsx` using the `omni-flow` pattern:

```tsx
import { Canvas, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { PanoViewState } from '../../stores/workspaceStore'

interface PanoVideoViewerProps {
  src: string
  paused: boolean
  currentTime: number
  muted: boolean
  viewState: PanoViewState
  onTimeChange: (time: number) => void
  onDurationChange: (duration: number) => void
  onViewChange: (view: PanoViewState) => void
  onError: (error: Error) => void
}

function DragRotateCamera({ viewState, onViewChange }: { viewState: PanoViewState; onViewChange: (view: PanoViewState) => void }) {
  const { camera, gl } = useThree()

  useEffect(() => {
    camera.position.set(0, 0, 0)
    camera.rotation.order = 'YXZ'
    camera.rotation.y = viewState.yaw
    camera.rotation.x = viewState.pitch
  }, [camera, viewState.pitch, viewState.yaw])

  useEffect(() => {
    const canvas = gl.domElement
    let dragging = false
    let last = { x: 0, y: 0 }

    const onDown = (event: PointerEvent) => {
      dragging = true
      last = { x: event.clientX, y: event.clientY }
      canvas.setPointerCapture(event.pointerId)
      canvas.style.cursor = 'grabbing'
    }

    const onMove = (event: PointerEvent) => {
      if (!dragging) return
      const dx = event.clientX - last.x
      const dy = event.clientY - last.y
      last = { x: event.clientX, y: event.clientY }
      const yaw = camera.rotation.y - dx * 0.004
      const pitch = Math.max(-Math.PI / 2.1, Math.min(Math.PI / 2.1, camera.rotation.x - dy * 0.004))
      camera.rotation.y = yaw
      camera.rotation.x = pitch
      onViewChange({ yaw, pitch, fov: viewState.fov })
    }

    const onUp = (event: PointerEvent) => {
      dragging = false
      canvas.releasePointerCapture(event.pointerId)
      canvas.style.cursor = 'grab'
    }

    canvas.style.cursor = 'grab'
    canvas.style.touchAction = 'none'
    canvas.addEventListener('pointerdown', onDown)
    canvas.addEventListener('pointermove', onMove)
    canvas.addEventListener('pointerup', onUp)
    canvas.addEventListener('pointercancel', onUp)
    return () => {
      canvas.removeEventListener('pointerdown', onDown)
      canvas.removeEventListener('pointermove', onMove)
      canvas.removeEventListener('pointerup', onUp)
      canvas.removeEventListener('pointercancel', onUp)
    }
  }, [camera, gl, onViewChange, viewState.fov])

  return null
}

function VideoSphere({ video }: { video: HTMLVideoElement }) {
  const texture = useMemo(() => {
    const value = new THREE.VideoTexture(video)
    value.colorSpace = THREE.SRGBColorSpace
    value.wrapS = THREE.RepeatWrapping
    value.repeat.x = -1
    value.offset.x = 1
    return value
  }, [video])

  useEffect(() => () => texture.dispose(), [texture])

  return (
    <mesh>
      <sphereGeometry args={[5, 64, 32]} />
      <meshBasicMaterial map={texture} side={THREE.BackSide} />
    </mesh>
  )
}

export default function PanoVideoViewer({ src, paused, currentTime, muted, viewState, onTimeChange, onDurationChange, onViewChange, onError }: PanoVideoViewerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  if (!videoRef.current) {
    const video = document.createElement('video')
    video.loop = true
    video.playsInline = true
    video.crossOrigin = 'anonymous'
    videoRef.current = video
  }
  const video = videoRef.current

  useEffect(() => {
    video.src = src
    video.muted = muted
    const onTime = () => onTimeChange(video.currentTime)
    const onDuration = () => onDurationChange(video.duration)
    const onVideoError = () => onError(new Error('Video failed to load'))
    video.addEventListener('timeupdate', onTime)
    video.addEventListener('durationchange', onDuration)
    video.addEventListener('error', onVideoError)
    return () => {
      video.pause()
      video.src = ''
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('durationchange', onDuration)
      video.removeEventListener('error', onVideoError)
    }
  }, [muted, onDurationChange, onError, onTimeChange, src, video])

  useEffect(() => {
    if (Math.abs(video.currentTime - currentTime) > 0.25) video.currentTime = currentTime
  }, [currentTime, video])

  useEffect(() => {
    video.muted = muted
  }, [muted, video])

  useEffect(() => {
    if (paused) {
      video.pause()
    } else {
      void video.play().catch((error: unknown) => onError(error instanceof Error ? error : new Error('Video playback failed')))
    }
  }, [onError, paused, video])

  return (
    <Canvas camera={{ position: [0, 0, 0.001], fov: viewState.fov, near: 0.001, far: 100 }} style={{ width: '100%', height: '100%', display: 'block' }} gl={{ antialias: true }}>
      <VideoSphere video={video} />
      <DragRotateCamera viewState={viewState} onViewChange={onViewChange} />
    </Canvas>
  )
}
```

- [ ] **Step 4: Create viewer controls**

Create `frontend/src/features/viewer/ViewerControls.tsx`:

```tsx
interface ViewerControlsProps {
  paused: boolean
  muted: boolean
  currentTime: number
  duration: number
  onPausedChange: (paused: boolean) => void
  onMutedChange: (muted: boolean) => void
  onSeek: (time: number) => void
  onResetView: () => void
}

export default function ViewerControls({ paused, muted, currentTime, duration, onPausedChange, onMutedChange, onSeek, onResetView }: ViewerControlsProps) {
  return (
    <div className="viewer-controls">
      <button type="button" onClick={() => onPausedChange(!paused)}>{paused ? '播放' : '暂停'}</button>
      <button type="button" onClick={() => onMutedChange(!muted)}>{muted ? '取消静音' : '静音'}</button>
      <input aria-label="播放进度" type="range" min={0} max={duration || 0} value={currentTime} onChange={(event) => onSeek(Number(event.target.value))} />
      <button type="button" onClick={onResetView}>重置视角</button>
    </div>
  )
}
```

- [ ] **Step 5: Run viewer test and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/viewer/PanoVideoViewer.test.tsx && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit panorama viewer**

Run:

```bash
rtk git add frontend/src/features/viewer && rtk git commit -m "feat: add panorama video viewer"
```

---

## Task 13: Comparison modes and viewer workspace integration

**Files:**
- Create: `frontend/src/features/viewer/SyncedPanoramaCompare.tsx`
- Create: `frontend/src/features/viewer/ABPanoramaCompare.tsx`
- Create: `frontend/src/features/viewer/SliderPanoramaCompare.tsx`
- Modify: `frontend/src/features/results/ResultPreviewWorkspace.tsx`
- Test: `frontend/src/features/viewer/ComparisonModes.test.tsx`

- [ ] **Step 1: Add comparison mode tests**

Create `frontend/src/features/viewer/ComparisonModes.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ABPanoramaCompare from './ABPanoramaCompare'

vi.mock('./PanoVideoViewer', () => ({ default: () => <div data-testid="pano-viewer" /> }))

describe('comparison modes', () => {
  it('renders A/B controls and one viewer', () => {
    render(<ABPanoramaCompare aSrc="/a.mp4" bSrc="/b.mp4" />)

    expect(screen.getByRole('button', { name: 'A 原始' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'B 超分' })).toBeInTheDocument()
    expect(screen.getAllByTestId('pano-viewer')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run comparison test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/viewer/ComparisonModes.test.tsx
```

Expected: FAIL because comparison components do not exist.

- [ ] **Step 3: Create A/B comparison**

Create `frontend/src/features/viewer/ABPanoramaCompare.tsx`:

```tsx
import { useState } from 'react'
import { initialWorkspaceState } from '../../stores/workspaceStore'
import PanoVideoViewer from './PanoVideoViewer'

interface ABPanoramaCompareProps {
  aSrc: string
  bSrc: string
}

export default function ABPanoramaCompare({ aSrc, bSrc }: ABPanoramaCompareProps) {
  const [active, setActive] = useState<'a' | 'b'>('a')
  const [state, setState] = useState(initialWorkspaceState)
  return (
    <div className="ab-compare">
      <div className="compare-inline-controls">
        <button type="button" onClick={() => setActive('a')}>A 原始</button>
        <button type="button" onClick={() => setActive('b')}>B 超分</button>
      </div>
      <PanoVideoViewer src={active === 'a' ? aSrc : bSrc} paused={state.paused} currentTime={state.currentTime} muted={state.muted} viewState={state.viewState} onTimeChange={(currentTime) => setState((next) => ({ ...next, currentTime }))} onDurationChange={() => undefined} onViewChange={(viewState) => setState((next) => ({ ...next, viewState }))} onError={() => undefined} />
    </div>
  )
}
```

- [ ] **Step 4: Create side-by-side and slider comparison**

Create `frontend/src/features/viewer/SyncedPanoramaCompare.tsx`:

```tsx
import { useState } from 'react'
import { initialWorkspaceState } from '../../stores/workspaceStore'
import PanoVideoViewer from './PanoVideoViewer'

interface SyncedPanoramaCompareProps {
  leftSrc: string
  rightSrc: string
}

export default function SyncedPanoramaCompare({ leftSrc, rightSrc }: SyncedPanoramaCompareProps) {
  const [state, setState] = useState(initialWorkspaceState)
  return (
    <div className="synced-compare">
      <PanoVideoViewer src={leftSrc} paused={state.paused} currentTime={state.currentTime} muted={state.muted} viewState={state.viewState} onTimeChange={(currentTime) => setState((next) => ({ ...next, currentTime }))} onDurationChange={() => undefined} onViewChange={(viewState) => setState((next) => ({ ...next, viewState }))} onError={() => undefined} />
      <PanoVideoViewer src={rightSrc} paused={state.paused} currentTime={state.currentTime} muted={state.muted} viewState={state.viewState} onTimeChange={() => undefined} onDurationChange={() => undefined} onViewChange={(viewState) => setState((next) => ({ ...next, viewState }))} onError={() => undefined} />
    </div>
  )
}
```

Create `frontend/src/features/viewer/SliderPanoramaCompare.tsx`:

```tsx
import { useState } from 'react'
import SyncedPanoramaCompare from './SyncedPanoramaCompare'

interface SliderPanoramaCompareProps {
  leftSrc: string
  rightSrc: string
}

export default function SliderPanoramaCompare({ leftSrc, rightSrc }: SliderPanoramaCompareProps) {
  const [split, setSplit] = useState(50)
  return (
    <div className="slider-compare" style={{ '--split': `${split}%` } as React.CSSProperties}>
      <SyncedPanoramaCompare leftSrc={leftSrc} rightSrc={rightSrc} />
      <input aria-label="对比分割" type="range" min={0} max={100} value={split} onChange={(event) => setSplit(Number(event.target.value))} />
    </div>
  )
}
```

- [ ] **Step 5: Wire modes into `ResultPreviewWorkspace`**

Replace `frontend/src/features/results/ResultPreviewWorkspace.tsx` with:

```tsx
import { useState } from 'react'
import { initialWorkspaceState } from '../../stores/workspaceStore'
import type { ComparisonMode, ResultSummary } from '../../types/result'
import ABPanoramaCompare from '../viewer/ABPanoramaCompare'
import PanoVideoViewer from '../viewer/PanoVideoViewer'
import SliderPanoramaCompare from '../viewer/SliderPanoramaCompare'
import SyncedPanoramaCompare from '../viewer/SyncedPanoramaCompare'
import ResultMetadataBar from './ResultMetadataBar'
import VersionStrip from './VersionStrip'

interface ResultPreviewWorkspaceProps {
  result: ResultSummary | null
  selectedVersionId: string | null
}

export default function ResultPreviewWorkspace({ result, selectedVersionId }: ResultPreviewWorkspaceProps) {
  const [mode, setMode] = useState<ComparisonMode>('side-by-side')
  const [viewerState, setViewerState] = useState(initialWorkspaceState)
  const [duration, setDuration] = useState(0)
  const selected = result?.versions.find((version) => version.version_id === selectedVersionId) ?? result?.versions[0] ?? null

  if (!result) {
    return <div className="result-workspace empty">提交或选择一个任务后查看结果。</div>
  }

  const source = result.versions[0]
  const current = selected ?? source
  const sourceUrl = source?.preview_url ?? source?.download_url ?? null
  const currentUrl = current?.preview_url ?? current?.download_url ?? null

  function renderViewer() {
    if (!sourceUrl || !currentUrl) return <div className="viewer-placeholder">360° 全景预览</div>
    if (mode === 'side-by-side') return <SyncedPanoramaCompare leftSrc={sourceUrl} rightSrc={currentUrl} />
    if (mode === 'slider') return <SliderPanoramaCompare leftSrc={sourceUrl} rightSrc={currentUrl} />
    if (mode === 'ab') return <ABPanoramaCompare aSrc={sourceUrl} bSrc={currentUrl} />
    return (
      <PanoVideoViewer
        src={currentUrl}
        paused={viewerState.paused}
        currentTime={viewerState.currentTime}
        muted={viewerState.muted}
        viewState={viewerState.viewState}
        onTimeChange={(currentTime) => setViewerState((next) => ({ ...next, currentTime }))}
        onDurationChange={setDuration}
        onViewChange={(viewState) => setViewerState((next) => ({ ...next, viewState }))}
        onError={() => undefined}
      />
    )
  }

  const modes: Array<{ value: ComparisonMode; label: string }> = [
    { value: 'side-by-side', label: '左右对比' },
    { value: 'single', label: '单看' },
    { value: 'slider', label: '滑块对比' },
    { value: 'ab', label: 'A/B 对比' },
  ]

  return (
    <div className="result-workspace">
      <header className="result-workspace-header">
        <div>
          <h2>结果预览 <span className="status-inline">● {result.status}</span></h2>
          <p>任务来源：{result.root_job_id}</p>
        </div>
        <div className="compare-tabs" aria-label="对比模式">
          {modes.map((item) => (
            <button key={item.value} className={mode === item.value ? 'active' : ''} type="button" onClick={() => setMode(item.value)}>{item.label}</button>
          ))}
        </div>
      </header>
      <div className="viewer-stage">{renderViewer()}</div>
      <VersionStrip versions={result.versions} selectedVersionId={current?.version_id ?? null} />
      <ResultMetadataBar version={current} />
      {duration > 0 ? <p className="preset-summary">当前视频时长：{Math.round(duration)} 秒</p> : null}
    </div>
  )
}
```

- [ ] **Step 6: Run comparison tests and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/features/viewer/ComparisonModes.test.tsx src/features/results/ResultPreviewWorkspace.test.tsx && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 7: Commit comparison modes**

Run:

```bash
rtk git add frontend/src/features && rtk git commit -m "feat: add panorama comparison modes"
```

---

## Task 14: Live API wiring in `App`

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Test: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add app integration test**

Create `frontend/src/App.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  it('loads runtime and result data from APIs', async () => {
    vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/runtime/summary') return new Response(JSON.stringify({ capacity: 1, available_capacity: 1, online_workers: 1, loading_workers: 0, busy_workers: 0, queued_jobs: 0, running_jobs: 0, cancelling_jobs: 0, runtime_warm: true }), { status: 200 })
      if (url === '/api/results') return new Response(JSON.stringify({ results: [{ result_id: 'res_job_1', root_job_id: 'job_1', prompt: 'A cinematic alpine valley at sunset', status: 'completed', selected_version_id: 'ver_job_1', created_at: '2026-05-02T12:00:00Z', updated_at: '2026-05-02T12:01:00Z', versions: [{ version_id: 'ver_job_1', job_id: 'job_1', type: 'original', label: '原始生成', status: 'succeeded', params: {} }] }] }), { status: 200 })
      return new Response('{}', { status: 404 })
    }))

    render(<App />)

    await waitFor(() => expect(screen.getByText('A cinematic alpine valley at sunset')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run app test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/App.test.tsx
```

Expected: FAIL because `App` still uses sample data.

- [ ] **Step 3: Update `AppShell` props**

Replace `frontend/src/components/AppShell.tsx` with:

```tsx
import type { RuntimeSummary } from '../types/runtime'
import type { CreateResultPayload, ResultSummary } from '../types/result'
import CreateTaskPanel from '../features/create/CreateTaskPanel'
import ResultPreviewWorkspace from '../features/results/ResultPreviewWorkspace'
import RecentTasksTable from '../features/tasks/RecentTasksTable'
import VersionUpscalePanel from '../features/versions/VersionUpscalePanel'
import RuntimeStatusBar from './RuntimeStatusBar'

interface AppShellProps {
  runtime: RuntimeSummary
  results: ResultSummary[]
  selectedResult: ResultSummary | null
  selectedVersionId: string | null
  onSelectVersion: (versionId: string) => void
  onCreateResult: (payload: CreateResultPayload) => void | Promise<void>
}

export default function AppShell({ runtime, results, selectedResult, selectedVersionId, onCreateResult }: AppShellProps) {
  return (
    <main className="workbench-shell">
      <header className="workbench-header">
        <h1>PanoWan 视频生成</h1>
        <RuntimeStatusBar runtime={runtime} />
      </header>
      <section className="workbench-grid" aria-label="PanoWan 结果工作台">
        <aside className="workbench-card create-region" aria-label="新建任务">
          <CreateTaskPanel onSubmit={onCreateResult} />
        </aside>
        <section className="workbench-card preview-region" aria-label="结果预览">
          <ResultPreviewWorkspace result={selectedResult} selectedVersionId={selectedVersionId} />
        </section>
        <aside className="workbench-card versions-region" aria-label="版本与超分">
          <VersionUpscalePanel result={selectedResult} />
        </aside>
      </section>
      <section className="workbench-card recent-region" aria-label="最近任务">
        <RecentTasksTable results={results} />
      </section>
    </main>
  )
}
```

Update `frontend/src/components/AppShell.test.tsx` to pass explicit result props:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import AppShell from './AppShell'
import { emptyRuntimeSummary } from '../stores/runtimeStore'

describe('AppShell', () => {
  it('renders the five workbench regions', () => {
    render(
      <AppShell
        runtime={emptyRuntimeSummary}
        results={[]}
        selectedResult={null}
        selectedVersionId={null}
        onSelectVersion={() => undefined}
        onCreateResult={() => undefined}
      />,
    )

    expect(screen.getByText('PanoWan 视频生成')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '新建任务' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '结果预览' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '版本与超分' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '最近任务' })).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: Update `App.tsx` to load APIs**

Replace `frontend/src/App.tsx` with:

```tsx
import { useEffect, useMemo, useState } from 'react'
import { connectWorkbenchEvents } from './api/eventClient'
import { createResult, fetchResults } from './api/resultClient'
import { fetchRuntimeSummary } from './api/runtimeClient'
import AppShell from './components/AppShell'
import { emptyRuntimeSummary } from './stores/runtimeStore'
import { selectInitialVersion, upsertResult } from './stores/resultStore'
import type { CreateResultPayload, ResultSummary } from './types/result'
import type { RuntimeSummary } from './types/runtime'

export default function App() {
  const [runtime, setRuntime] = useState<RuntimeSummary>(emptyRuntimeSummary)
  const [results, setResults] = useState<ResultSummary[]>([])
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null)

  useEffect(() => {
    void fetchRuntimeSummary().then(setRuntime)
    void fetchResults().then((loaded) => {
      setResults(loaded)
      const first = loaded[0]
      if (first) {
        setSelectedResultId(first.result_id)
        setSelectedVersionId(selectInitialVersion(first))
      }
    })
  }, [])

  useEffect(() => {
    const source = connectWorkbenchEvents(() => {
      void fetchRuntimeSummary().then(setRuntime)
      void fetchResults().then(setResults)
    })
    return () => source.close()
  }, [])

  const selectedResult = useMemo(() => results.find((result) => result.result_id === selectedResultId) ?? results[0] ?? null, [results, selectedResultId])

  async function handleCreateResult(payload: CreateResultPayload) {
    const result = await createResult(payload)
    setResults((current) => upsertResult(current, result))
    setSelectedResultId(result.result_id)
    setSelectedVersionId(selectInitialVersion(result))
  }

  return <AppShell runtime={runtime} results={results} selectedResult={selectedResult} selectedVersionId={selectedVersionId} onSelectVersion={setSelectedVersionId} onCreateResult={handleCreateResult} />
}
```

- [ ] **Step 5: Run app tests and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/App.test.tsx && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit live API wiring**

Run:

```bash
rtk git add frontend/src && rtk git commit -m "feat: connect workbench to api"
```

---

## Task 15: Task governance actions and failed cleanup

**Files:**
- Create: `frontend/src/api/taskClient.ts`
- Modify: `frontend/src/features/tasks/TaskActionsMenu.tsx`
- Modify: `frontend/src/features/tasks/RecentTasksTable.tsx`
- Test: `frontend/src/api/taskClient.test.ts`

- [ ] **Step 1: Add task client tests**

Create `frontend/src/api/taskClient.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { cancelJob, clearFailedJobs } from './taskClient'

describe('taskClient', () => {
  it('posts cancel request', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ status: 'cancelling' }), { status: 200 })))

    await cancelJob('job_1')

    expect(fetch).toHaveBeenCalledWith('/api/jobs/job_1/cancel', expect.objectContaining({ method: 'POST' }))
  })

  it('deletes failed jobs', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ deleted_count: 2 }), { status: 200 })))

    const result = await clearFailedJobs()

    expect(result.deleted_count).toBe(2)
  })
})
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
rtk npm --prefix frontend run test -- src/api/taskClient.test.ts
```

Expected: FAIL because `taskClient.ts` does not exist.

- [ ] **Step 3: Create task client**

Create `frontend/src/api/taskClient.ts`:

```ts
import { requestJson } from './client'

export function cancelJob(jobId: string): Promise<unknown> {
  return requestJson(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
}

export function escalateCancelJob(jobId: string): Promise<unknown> {
  return requestJson(`/api/jobs/${jobId}/cancel/escalate`, { method: 'POST' })
}

export function retryCancelJob(jobId: string): Promise<unknown> {
  return requestJson(`/api/jobs/${jobId}/cancel/retry`, { method: 'POST' })
}

export function clearFailedJobs(): Promise<{ deleted_count: number }> {
  return requestJson('/api/jobs/failed', { method: 'DELETE' })
}
```

- [ ] **Step 4: Update task actions UI**

Replace `frontend/src/features/tasks/TaskActionsMenu.tsx` with:

```tsx
import type { JobStatus } from '../../types/result'

interface TaskActionsMenuProps {
  jobId: string
  status: JobStatus
  downloadUrl?: string | null
  onCancel: (jobId: string) => void | Promise<void>
  onEscalateCancel: (jobId: string) => void | Promise<void>
  onRetryCancel: (jobId: string) => void | Promise<void>
}

export default function TaskActionsMenu({ jobId, status, downloadUrl, onCancel, onEscalateCancel, onRetryCancel }: TaskActionsMenuProps) {
  const canCancel = status === 'queued' || status === 'claimed' || status === 'running'
  const canEscalate = status === 'cancelling'
  const canRetry = status === 'failed'
  return (
    <div className="task-actions">
      {downloadUrl ? <a className="table-action" href={downloadUrl}>下载</a> : null}
      {canCancel ? <button className="table-action" type="button" onClick={() => void onCancel(jobId)}>取消</button> : null}
      {canEscalate ? <button className="table-action" type="button" title="取消长时间未完成时使用强制取消" onClick={() => void onEscalateCancel(jobId)}>强制取消</button> : null}
      {canRetry ? <button className="table-action" type="button" title="仅对取消超时类失败重试取消" onClick={() => void onRetryCancel(jobId)}>重试取消</button> : null}
      <button className="icon-button" type="button" aria-label="更多操作">⋯</button>
    </div>
  )
}
```

Replace `frontend/src/features/tasks/RecentTasksTable.tsx` with:

```tsx
import type { ResultSummary } from '../../types/result'
import TaskActionsMenu from './TaskActionsMenu'

interface RecentTasksTableProps {
  results: ResultSummary[]
  onCancelJob?: (jobId: string) => void | Promise<void>
  onEscalateCancelJob?: (jobId: string) => void | Promise<void>
  onRetryCancelJob?: (jobId: string) => void | Promise<void>
}

export default function RecentTasksTable({ results, onCancelJob = () => undefined, onEscalateCancelJob = () => undefined, onRetryCancelJob = () => undefined }: RecentTasksTableProps) {
  return (
    <div className="recent-tasks-table">
      <header><h2>最近任务 <span>{results.length}</span></h2></header>
      <table>
        <thead><tr><th>缩略图</th><th>状态</th><th>Prompt</th><th>版本</th><th>操作</th></tr></thead>
        <tbody>
          {results.map((result) => {
            const selected = result.versions.find((version) => version.version_id === result.selected_version_id) ?? result.versions[0]
            return (
              <tr key={result.result_id}>
                <td><div className="thumbnail-cell" /></td>
                <td>{result.status}</td>
                <td>{result.prompt}</td>
                <td>{result.versions.map((version) => version.label).join(' / ')}</td>
                <td>
                  {selected ? (
                    <TaskActionsMenu
                      jobId={selected.job_id}
                      status={selected.status}
                      downloadUrl={selected.download_url}
                      onCancel={onCancelJob}
                      onEscalateCancel={onEscalateCancelJob}
                      onRetryCancel={onRetryCancelJob}
                    />
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
```

Append to `frontend/src/styles/app.css`:

```css
.task-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.table-action {
  border: 0;
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: rgba(34, 42, 53, 0.12) 0 0 0 1px;
  padding: 7px 9px;
  text-decoration: none;
  cursor: pointer;
}
```

- [ ] **Step 5: Run task client tests and build**

Run:

```bash
rtk npm --prefix frontend run test -- src/api/taskClient.test.ts && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit task governance client**

Run:

```bash
rtk git add frontend/src && rtk git commit -m "feat: add task governance actions"
```

---

## Task 16: Route old job governance endpoints under `/api/jobs`

**Files:**
- Modify: `app/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing `/api/jobs` governance tests**

Append these tests inside `ApiTests` in `tests/test_api.py`:

```python
    def test_api_cancel_job_route_matches_legacy_cancel_behavior(self) -> None:
        api._create_job_record(
            "api-cancel-queued",
            "prompt",
            os.path.join(self.temp_dir.name, "outputs", "api-cancel-queued.mp4"),
            {"width": 448, "height": 224},
        )

        response = self.client.post("/api/jobs/api-cancel-queued/cancel", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

    def test_api_escalate_cancel_route_matches_legacy_behavior(self) -> None:
        backend = api.get_job_backend()
        backend.create_job({"job_id": "api-cancel-running", "status": "queued", "type": "generate"})
        backend.claim_next_job(worker_id="worker-1")
        backend.mark_running("api-cancel-running", "worker-1")
        backend.request_cancellation("api-cancel-running", worker_id="worker-1")

        response = self.client.post("/api/jobs/api-cancel-running/cancel/escalate", json={})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "cancelling")
        self.assertEqual(payload["cancel_mode"], "escalated")

    def test_api_delete_failed_jobs_route_matches_legacy_behavior(self) -> None:
        api._create_job_record(
            "api-failed",
            "prompt",
            os.path.join(self.temp_dir.name, "outputs", "api-failed.mp4"),
            {"width": 448, "height": 224},
        )
        api._update_job("api-failed", status="failed", error="boom", finished_at="now")

        response = self.client.delete("/api/jobs/failed")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_count"], 1)

    def test_api_download_job_route_matches_legacy_behavior(self) -> None:
        job_id = "api-download"
        output_path = os.path.join(self.temp_dir.name, "outputs", "api-download.mp4")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as handle:
            handle.write(b"video-bytes")
        api._create_job_record(job_id, "prompt", output_path, {"width": 448, "height": 224})
        api._update_job(job_id, status="succeeded", output_path=output_path, finished_at="now")

        response = self.client.get(f"/api/jobs/{job_id}/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-job-id"], job_id)
        self.assertEqual(response.content, b"video-bytes")
```

Run:

```bash
rtk uv run python -m unittest tests.test_api.ApiTests.test_api_cancel_job_route_matches_legacy_cancel_behavior tests.test_api.ApiTests.test_api_escalate_cancel_route_matches_legacy_behavior tests.test_api.ApiTests.test_api_delete_failed_jobs_route_matches_legacy_behavior tests.test_api.ApiTests.test_api_download_job_route_matches_legacy_behavior
```

Expected: FAIL with 404 responses for `/api/jobs` routes.

- [ ] **Step 2: Add route aliases in `app/api.py`**

Add decorators to existing governance functions or wrapper functions:

```python
@app.post("/api/jobs/{job_id}/cancel")
def cancel_job_api(job_id: str) -> dict[str, Any]:
    return cancel_job(job_id)


@app.post("/api/jobs/{job_id}/cancel/escalate")
def escalate_cancel_job_api(job_id: str) -> dict[str, Any]:
    return escalate_cancel_job_endpoint(job_id)


@app.delete("/api/jobs/failed")
def delete_failed_jobs_api() -> dict[str, Any]:
    return delete_failed_jobs_endpoint()


@app.get("/api/jobs/{job_id}/download")
def download_job_api(job_id: str) -> FileResponse:
    return download_job(job_id)
```

- [ ] **Step 3: Run API governance tests**

Run:

```bash
rtk uv run python -m unittest tests.test_api
```

Expected: PASS.

- [ ] **Step 4: Commit `/api/jobs` governance routes**

Run:

```bash
rtk git add app/api.py tests/test_api.py && rtk git commit -m "feat: namespace job governance api"
```

---

## Task 17: Remove legacy single-page UI

**Files:**
- Delete: `app/static/index.html`
- Modify: tests that still reference `app/static/index.html`

- [ ] **Step 1: Search for legacy static references**

Run:

```bash
rtk grep "app/static/index.html\|fetch(\"/jobs\"\|/jobs/events\|id=\"job-table-body\""
```

Expected: references only in deleted legacy tests or historical docs.

- [ ] **Step 2: Delete legacy static UI file**

Run:

```bash
rtk git rm app/static/index.html
```

Expected: file removed from git.

- [ ] **Step 3: Run backend tests affected by root/static behavior**

Run:

```bash
rtk uv run python -m unittest tests.test_static_ui tests.test_api
```

Expected: PASS.

- [ ] **Step 4: Commit legacy UI removal**

Run:

```bash
rtk git add tests/test_static_ui.py app/api.py app/settings.py && rtk git commit -m "refactor: remove legacy static ui"
```

---

## Task 18: End-to-end build, browser verification, and final cleanup

**Files:**
- No planned source edits; use this task only for verification and tiny fixes discovered by the commands below.
- If `rtk grep "app/static/index.html"` returns a maintained doc path, update that doc to say the React build is served from `frontend/dist`.

- [ ] **Step 1: Run full backend test suite**

Run:

```bash
rtk uv run python -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 2: Run frontend tests and build**

Run:

```bash
rtk npm --prefix frontend run test && rtk npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 3: Start API for manual verification**

Run in a long-running terminal:

```bash
DEV_MODE=1 rtk uv run python -m app.api_service
```

Expected: API starts on configured host/port and serves React build at `/`.

- [ ] **Step 4: Verify browser golden path**

Open the app in a browser and verify:

1. Top bar shows capacity, Worker, queue, Runtime, and auto-refresh pills.
2. Left create panel submits a result.
3. Center workbench selects the new result.
4. Right panel shows original and upscale versions.
5. 360° preview accepts mouse drag.
6. A/B mode keeps the same view and time while switching source.
7. Side-by-side mode shares drag view between viewers.
8. Slider mode changes the comparison split.
9. Recent tasks table shows status, prompt, version labels, and actions.
10. Browser console has no errors.

- [ ] **Step 5: Stop the dev server**

Stop the terminal process with Ctrl+C.

- [ ] **Step 6: Run final git status**

Run:

```bash
rtk git status --short
```

Expected: clean working tree after all task commits.

---

## Self-Review Checklist

### Spec coverage

- Result workbench layout: covered by Tasks 9, 10, and 11.
- Result/version backend model: covered by Tasks 1, 2, and 3.
- Result-aware SSE: covered by Task 4.
- React/Vite TypeScript frontend: covered by Task 6.
- API clients and stores: covered by Tasks 7 and 8.
- 360° panorama viewer: covered by Task 12.
- Comparison modes: covered by Task 13.
- Task governance: covered by Tasks 15 and 16.
- FastAPI React build root: covered by Task 5.
- Legacy UI removal: covered by Task 17.
- Full test and browser verification: covered by Task 18.

### Placeholder scan

This plan intentionally avoids unresolved placeholders. Where implementation details depend on current code shape, the task gives a concrete target behavior, exact paths, commands, and code snippets.

### Type consistency

The plan consistently uses:

- `ResultSummary`
- `ResultVersion`
- `CreateResultPayload`
- `CreateUpscalePayload`
- `RuntimeSummary`
- `PanoViewState`
- `ComparisonMode`
- `result_id`
- `version_id`
- `job_id`

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-react-result-workbench-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
