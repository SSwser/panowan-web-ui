from dataclasses import replace
import importlib.util
import json
import logging
import os
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.testclient import TestClient
    from app import api
    from app.jobs import LocalWorkerRegistry
    from app.upscaler import UPSCALE_BACKENDS


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        patched_settings = replace(
            api.settings,
            output_dir=os.path.join(self.temp_dir.name, "outputs"),
            job_store_path=os.path.join(self.temp_dir.name, "jobs.json"),
            worker_store_path=os.path.join(self.temp_dir.name, "workers.json"),
        )
        self.settings_patch = patch("app.api.settings", patched_settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        # Backend state lives on the per-test tmpdir stores; no module globals to clear.
        self.client = TestClient(api.app)

    def _seed_upscale_worker(self, models: list[str] | None = None) -> None:
        LocalWorkerRegistry(api.settings.worker_store_path).upsert_worker(
            "test-worker",
            {
                "status": "online",
                "capabilities": ["upscale"],
                "available_upscale_models": models or ["realesrgan-animevideov3"],
                "max_concurrent_jobs": 1,
                "running_jobs": 0,
            },
        )

    def test_healthcheck_reports_path_status(self) -> None:
        path_exists = {
            api.settings.panowan_engine_dir: True,
            api.settings.wan_diffusion_absolute_path: True,
            api.settings.wan_t5_absolute_path: False,
            api.settings.lora_absolute_path: False,
        }

        with patch("app.api.os.path.exists", side_effect=path_exists.get):
            result = api.healthcheck()

        self.assertEqual(
            result,
            {
                "status": "starting",
                "service_started": True,
                "model_ready": False,
                "panowan_engine_dir_exists": True,
                "wan_model_exists": False,
                "lora_exists": False,
            },
        )

    def test_healthcheck_reports_ready_when_models_exist(self) -> None:
        with patch("app.api.os.path.exists", return_value=True):
            result = api.healthcheck()

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["service_started"])
        self.assertTrue(result["model_ready"])
        self.assertTrue(result["wan_model_exists"])
        self.assertTrue(result["lora_exists"])

    def test_access_log_filter_is_registered_once(self) -> None:
        logger = logging.getLogger("uvicorn.access")
        before = [
            flt
            for flt in logger.filters
            if isinstance(flt, api._HealthCheckAccessFilter)
        ]

        api._configure_access_log_filter()

        after = [
            flt
            for flt in logger.filters
            if isinstance(flt, api._HealthCheckAccessFilter)
        ]
        self.assertGreaterEqual(len(before), 1)
        self.assertEqual(len(after), len(before))

    def test_collect_job_store_events_detects_worker_completion(self) -> None:
        record = api._create_job_record(
            "job-1",
            "prompt",
            os.path.join(self.temp_dir.name, "outputs", "job-1.mp4"),
            {"num_inference_steps": 10, "width": 448, "height": 224},
        )
        snapshots = {record["job_id"]: api._job_event_snapshot(record)}

        api.get_job_backend().claim_next_job(worker_id="worker-1")
        api.get_job_backend().complete_job(
            "job-1",
            os.path.join(self.temp_dir.name, "outputs", "job-1.mp4"),
        )

        snapshots, events = api._collect_job_store_events(snapshots)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "job_updated")
        payload = json.loads(events[0]["data"])
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(snapshots["job-1"]["status"], "completed")

    def test_update_job_broadcasts_full_snapshot(self) -> None:
        record = api._create_job_record(
            "job-1",
            "prompt",
            os.path.join(self.temp_dir.name, "outputs", "job-1.mp4"),
            {"num_inference_steps": 10, "width": 448, "height": 224},
        )

        with unittest.mock.patch.object(api, "broadcast_job_event") as broadcast:
            updated = api._update_job(
                record["job_id"],
                status="failed",
                finished_at="done",
                error="boom",
            )

        broadcast.assert_called_once_with("job_updated", updated)

    def test_collect_job_store_events_detects_deleted_jobs(self) -> None:
        record = api._create_job_record(
            "job-1",
            "prompt",
            os.path.join(self.temp_dir.name, "outputs", "job-1.mp4"),
            {"num_inference_steps": 10, "width": 448, "height": 224},
        )
        snapshots = {record["job_id"]: api._job_event_snapshot(record)}

        api.get_job_backend().delete_failed_jobs()
        api.get_job_backend().update_job(
            "job-1",
            status="failed",
            finished_at="done",
            error="boom",
        )
        api.get_job_backend().delete_failed_jobs()

        snapshots, events = api._collect_job_store_events(snapshots)

        self.assertEqual(
            events,
            [
                {
                    "event": "job_deleted",
                    "data": json.dumps({"job_id": "job-1"}, ensure_ascii=False),
                }
            ],
        )
        self.assertEqual(snapshots, {})

    def test_generate_returns_queued_job_metadata(self) -> None:
        response = api.generate({"prompt": "test"})

        self.assertEqual(response["status"], "queued")
        self.assertIn("job_id", response)
        self.assertTrue(response["output_path"].endswith(f"{response['job_id']}.mp4"))
        self.assertEqual(
            response["download_url"], f"/jobs/{response['job_id']}/download"
        )

        with open(api.settings.job_store_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)

        self.assertEqual(
            persisted["jobs"][response["job_id"]]["status"],
            "queued",
        )

    def test_generate_creates_queued_job_without_running_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "RUNTIME_DIR": tmp,
                    "JOB_STORE_PATH": f"{tmp}/jobs.json",
                    "OUTPUT_DIR": f"{tmp}/outputs",
                },
                clear=True,
            ):
                from app.jobs.local import LocalJobBackend
                from app.settings import load_settings

                loaded = load_settings()
                backend = LocalJobBackend(loaded.job_store_path)
                record = backend.create_job(
                    {
                        "job_id": "job-1",
                        "status": "queued",
                        "type": "generate",
                        "prompt": "sky",
                        "params": {"width": 896, "height": 448},
                        "output_path": f"{tmp}/outputs/output_job-1.mp4",
                    }
                )

                self.assertEqual(record["status"], "queued")

    def test_generate_endpoint_only_queues_job(self) -> None:
        response = self.client.post("/generate", json={"prompt": "sky"})

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        job = self.client.get(f"/jobs/{payload['job_id']}").json()
        self.assertEqual(job["status"], "queued")

    def test_restore_jobs_marks_running_job_failed_after_restart(self) -> None:
        completed_output = os.path.join(self.temp_dir.name, "outputs", "done.mp4")
        os.makedirs(os.path.dirname(completed_output), exist_ok=True)
        with open(completed_output, "wb") as handle:
            handle.write(b"video")

        os.makedirs(os.path.dirname(api.settings.job_store_path), exist_ok=True)
        with open(api.settings.job_store_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "jobs": {
                        "queued-job": {
                            "job_id": "queued-job",
                            "status": "running",
                            "prompt": "still working",
                            "output_path": os.path.join(
                                self.temp_dir.name, "outputs", "queued.mp4"
                            ),
                            "created_at": "now",
                            "started_at": "now",
                            "finished_at": None,
                            "error": None,
                        },
                        "done-job": {
                            "job_id": "done-job",
                            "status": "completed",
                            "prompt": "finished",
                            "output_path": completed_output,
                            "created_at": "now",
                            "started_at": "now",
                            "finished_at": "later",
                            "error": None,
                        },
                    }
                },
                handle,
            )

        api.get_job_backend().restore()

        queued_job = api._get_job("queued-job")
        done_job = api._get_job("done-job")

        self.assertEqual(queued_job["status"], "failed")
        self.assertEqual(
            queued_job["error"],
            "Service restarted before the job completed",
        )
        self.assertEqual(done_job["status"], "completed")

    def test_root_returns_index_html(self) -> None:
        response = api.root()

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(response.media_type, "text/html")
        self.assertTrue(response.path.endswith("index.html"))

    def test_list_jobs_returns_sorted_jobs(self) -> None:
        backend = api.get_job_backend()
        backend.create_job(
            {
                "job_id": "job-a",
                "status": "completed",
                "prompt": "first",
                "output_path": "",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        backend.create_job(
            {
                "job_id": "job-b",
                "status": "queued",
                "prompt": "second",
                "output_path": "",
                "created_at": "2026-06-01T00:00:00+00:00",
            }
        )

        result = api.list_jobs()

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        # newer first
        self.assertEqual(result[0]["job_id"], "job-b")
        self.assertEqual(result[1]["job_id"], "job-a")

    def test_create_job_record_includes_type_field(self) -> None:
        record = api._create_job_record("test-id", "prompt", "/out.mp4", {})
        self.assertEqual(record["type"], "generate")
        self.assertIsNone(record["source_job_id"])
        self.assertIsNone(record["upscale_params"])

    def test_download_returns_mp4_file_response(self) -> None:
        job_id = "job-1"
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"video-bytes")
            temp_path = temp_file.name

        self.addCleanup(lambda: os.path.exists(temp_path) and os.unlink(temp_path))

        api._create_job_record(job_id, "test", temp_path, {})
        api._update_job(
            job_id,
            status="completed",
            started_at="now",
            finished_at="now",
            output_path=temp_path,
        )

        response = api.download_job(job_id)

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(response.path, temp_path)
        self.assertEqual(response.media_type, "video/mp4")
        self.assertEqual(response.headers["x-job-id"], job_id)

    def _seed_completed_source(
        self,
        source_id: str,
        *,
        output_path: str = "/fake/output.mp4",
        params: dict | None = None,
        prompt: str = "test",
    ) -> None:
        api._create_job_record(
            source_id,
            prompt,
            output_path,
            params or {"width": 448, "height": 224},
        )
        api._update_job(
            source_id,
            status="completed",
            started_at="now",
            finished_at="now",
            output_path=output_path,
        )

    def test_upscale_creates_new_job_linked_to_source(self) -> None:
        source_id = "source-1"
        self._seed_completed_source(source_id)
        self._seed_upscale_worker()

        with patch("app.api.os.path.exists", return_value=True):
            response = api.upscale(
                {
                    "source_job_id": source_id,
                    "model": "realesrgan-animevideov3",
                    "scale": 2,
                }
            )

        self.assertEqual(response["status"], "queued")
        self.assertEqual(response["type"], "upscale")
        self.assertEqual(response["source_job_id"], source_id)
        self.assertEqual(response["upscale_params"]["model"], "realesrgan-animevideov3")
        self.assertEqual(response["upscale_params"]["scale"], 2)

    def test_upscale_rejects_non_completed_source(self) -> None:
        api._create_job_record("running-1", "", "", {})
        api._update_job("running-1", status="running", started_at="now")

        with self.assertRaises(HTTPException) as ctx:
            api.upscale({"source_job_id": "running-1"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upscale_rejects_unknown_model(self) -> None:
        self._seed_completed_source("done-1", output_path="/out.mp4")

        with patch("app.api.os.path.exists", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                api.upscale({"source_job_id": "done-1", "model": "nonexistent"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upscale_accepts_registered_model(self) -> None:
        self._seed_completed_source("done-avail", output_path="/out.mp4")
        self._seed_upscale_worker()

        with patch("app.api.os.path.exists", return_value=True):
            response = api.upscale(
                {
                    "source_job_id": "done-avail",
                    "model": "realesrgan-animevideov3",
                }
            )

        self.assertEqual(response["type"], "upscale")
        self.assertEqual(response["upscale_params"]["model"], "realesrgan-animevideov3")

    def test_upscale_rejects_model_without_online_worker(self) -> None:
        self._seed_completed_source("done-no-worker", output_path="/out.mp4")

        with patch("app.api.os.path.exists", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                api.upscale(
                    {
                        "source_job_id": "done-no-worker",
                        "model": "realesrgan-animevideov3",
                    }
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("No online worker", ctx.exception.detail)

    def test_upscale_rejects_invalid_seedvr2_target_dimensions(self) -> None:
        self._seed_completed_source(
            "done-seedvr2",
            output_path="/out.mp4",
            params={"width": 896, "height": 448},
        )
        self._seed_upscale_worker(["seedvr2-3b"])

        with patch("app.api.os.path.exists", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                api.upscale(
                    {
                        "source_job_id": "done-seedvr2",
                        "model": "seedvr2-3b",
                        "target_width": 1345,
                        "target_height": 896,
                    }
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("multiple of 32", ctx.exception.detail)

    def test_upscale_rejects_target_dimensions_for_realesrgan(self) -> None:
        self._seed_completed_source(
            "done-realesrgan",
            output_path="/out.mp4",
            params={"width": 896, "height": 448},
        )
        self._seed_upscale_worker(["realesrgan-animevideov3"])

        with patch("app.api.os.path.exists", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                api.upscale(
                    {
                        "source_job_id": "done-realesrgan",
                        "model": "realesrgan-animevideov3",
                        "target_width": 1280,
                        "target_height": 720,
                    }
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("does not support target_width/target_height", ctx.exception.detail)

    def test_upscale_rejects_missing_source_job(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            api.upscale({"source_job_id": "nonexistent"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upscale_rejects_missing_source_file(self) -> None:
        self._seed_completed_source("done-2", output_path="/nonexistent.mp4")

        with patch("app.api.os.path.exists", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                api.upscale({"source_job_id": "done-2"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_cancel_queued_job_succeeds(self) -> None:
        api._create_job_record("q1", "", "", {})

        with unittest.mock.patch.object(api, "broadcast_job_event") as broadcast:
            result = api.cancel_job("q1", force=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Cancelled by user")
        broadcast.assert_called_once_with("job_updated", result)

    def test_cancel_running_without_force_returns_warning(self) -> None:
        # Subprocess termination now lives in the worker (Task 6); the API
        # cannot return a real PID and just emits the warning shape.
        api._create_job_record("r1", "", "", {})
        api._update_job("r1", status="running", started_at="now")

        result = api.cancel_job("r1", force=False)

        self.assertTrue(result.get("warning"))
        self.assertEqual(result["status"], "running")
        self.assertIsNone(result["pid"])

    def test_cancel_completed_job_raises(self) -> None:
        api._create_job_record("c1", "", "/out.mp4", {})
        api._update_job("c1", status="completed", finished_at="now")

        with self.assertRaises(HTTPException) as ctx:
            api.cancel_job("c1", force=False)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_cancel_nonexistent_job_raises(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            api.cancel_job("nonexistent", force=False)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cancel_running_with_force_marks_failed(self) -> None:
        # Subprocess termination now lives in the worker (Task 6). Force-cancel
        # from the API just flips the status; the worker must observe and abort.
        api._create_job_record("r2", "", "", {})
        api._update_job("r2", status="running", started_at="now")

        result = api.cancel_job("r2", force=True)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Cancelled by user")

    def test_upscale_and_cancel_queued_job(self) -> None:
        """End-to-end: create source job, upscale it, cancel the upscale."""
        source_id = "src-1"
        self._seed_completed_source(source_id, output_path="/fake/out.mp4")
        self._seed_upscale_worker()

        with patch("app.api.os.path.exists", return_value=True):
            resp = api.upscale(
                {
                    "source_job_id": source_id,
                    "model": "realesrgan-animevideov3",
                    "scale": 2,
                }
            )

        upscale_id = resp["job_id"]
        self.assertEqual(resp["type"], "upscale")

        # Cancel the queued upscale job
        result = api.cancel_job(upscale_id, force=False)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Cancelled by user")

    def test_upscale_job_record_has_source_info(self) -> None:
        source_id = "src-2"
        self._seed_completed_source(
            source_id,
            output_path="/fake/out2.mp4",
            params={"width": 896, "height": 448},
            prompt="hello",
        )
        self._seed_upscale_worker(["seedvr2-3b"])

        with patch("app.api.os.path.exists", return_value=True):
            resp = api.upscale(
                {"source_job_id": source_id, "model": "seedvr2-3b", "scale": 2}
            )

        job = api._get_job(resp["job_id"])
        self.assertEqual(job["type"], "upscale")
        self.assertEqual(job["source_job_id"], source_id)
        self.assertEqual(job["upscale_params"]["model"], "seedvr2-3b")
        self.assertEqual(job["upscale_params"]["scale"], 2)
        self.assertEqual(job["upscale_params"]["target_width"], 1792)
        self.assertEqual(job["upscale_params"]["target_height"], 896)
        self.assertEqual(job["source_output_path"], "/fake/out2.mp4")
        self.assertEqual(job["payload"]["source_output_path"], "/fake/out2.mp4")
