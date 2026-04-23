from dataclasses import replace
import importlib.util
import json
import os
import tempfile
import unittest
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from fastapi import BackgroundTasks, HTTPException
    from fastapi.responses import FileResponse
    from app import api


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        patched_settings = replace(
            api.settings,
            output_dir=os.path.join(self.temp_dir.name, "outputs"),
            job_store_path=os.path.join(self.temp_dir.name, "jobs.json"),
        )
        self.settings_patch = patch("app.api.settings", patched_settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(api._jobs.clear)
        api._jobs.clear()

    def test_healthcheck_reports_path_status(self) -> None:
        path_exists = {
            api.settings.panowan_dir: True,
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
                "panowan_dir_exists": True,
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

    def test_generate_queues_background_job_and_marks_failure(self) -> None:
        with patch("app.api.generate_video", side_effect=TimeoutError("too slow")):
            background_tasks = BackgroundTasks()
            response = api.generate({"prompt": "test"}, background_tasks)

        self.assertEqual(response["status"], "queued")
        self.assertEqual(len(background_tasks.tasks), 1)

        task = background_tasks.tasks[0]
        task.func(*task.args, **task.kwargs)

        job = api.get_job(response["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "too slow")

    def test_generate_returns_queued_job_metadata(self) -> None:
        with patch("app.api.generate_video") as mock_generate_video:
            background_tasks = BackgroundTasks()
            response = api.generate({"prompt": "test"}, background_tasks)

        self.assertEqual(response["status"], "queued")
        self.assertIn("job_id", response)
        self.assertEqual(len(background_tasks.tasks), 1)
        self.assertTrue(response["output_path"].endswith(f"{response['job_id']}.mp4"))
        self.assertEqual(response["download_url"], f"/jobs/{response['job_id']}/download")
        mock_generate_video.assert_not_called()

        with open(api.settings.job_store_path, "r", encoding="utf-8") as handle:
            persisted = json.load(handle)

        self.assertEqual(
            persisted["jobs"][response["job_id"]]["status"],
            "queued",
        )

    def test_restore_jobs_marks_running_job_failed_after_restart(self) -> None:
        completed_output = os.path.join(self.temp_dir.name, "outputs", "done.mp4")
        os.makedirs(os.path.dirname(completed_output), exist_ok=True)
        with open(completed_output, "wb") as handle:
            handle.write(b"video")

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

        api._restore_jobs_from_disk()

        queued_job = api.get_job("queued-job")
        done_job = api.get_job("done-job")

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
        with patch.dict(
            api._jobs,
            {
                "job-a": {
                    "job_id": "job-a",
                    "status": "completed",
                    "prompt": "first",
                    "output_path": "",
                    "download_url": "/jobs/job-a/download",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                },
                "job-b": {
                    "job_id": "job-b",
                    "status": "queued",
                    "prompt": "second",
                    "output_path": "",
                    "download_url": "/jobs/job-b/download",
                    "created_at": "2026-06-01T00:00:00+00:00",
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                },
            },
            clear=True,
        ):
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

    def test_normalize_job_record_adds_type_for_legacy_jobs(self) -> None:
        legacy = {
            "job_id": "old-job",
            "status": "completed",
            "output_path": "/exists.mp4",
        }
        with patch("app.api.os.path.exists", return_value=True):
            normalized = api._normalize_job_record("old-job", legacy)
        self.assertEqual(normalized["type"], "generate")
        self.assertIsNone(normalized["source_job_id"])
        self.assertIsNone(normalized["upscale_params"])

    def test_download_returns_mp4_file_response(self) -> None:
        job_id = "job-1"
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"video-bytes")
            temp_path = temp_file.name

        self.addCleanup(lambda: os.path.exists(temp_path) and os.unlink(temp_path))

        with patch.dict(
            api._jobs,
            {
                job_id: {
                    "job_id": job_id,
                    "status": "completed",
                    "prompt": "test",
                    "output_path": temp_path,
                    "download_url": f"/jobs/{job_id}/download",
                    "created_at": "now",
                    "started_at": "now",
                    "finished_at": "now",
                    "error": None,
                }
            },
            clear=True,
        ):
            response = api.download_job(job_id)

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(response.path, temp_path)
        self.assertEqual(response.media_type, "video/mp4")
        self.assertEqual(response.headers["x-job-id"], job_id)

    def test_upscale_creates_new_job_linked_to_source(self) -> None:
        # Create a completed source job in _jobs
        source_id = "source-1"
        with patch.dict(api._jobs, clear=True):
            api._jobs[source_id] = {
                "job_id": source_id, "status": "completed", "type": "generate",
                "prompt": "test", "params": {"width": 448, "height": 224},
                "output_path": "/fake/output.mp4",
                "download_url": f"/jobs/{source_id}/download",
                "created_at": "now", "started_at": "now", "finished_at": "now",
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            with patch("app.api.os.path.exists", return_value=True):
                background_tasks = BackgroundTasks()
                response = api.upscale({"source_job_id": source_id, "model": "realesrgan-animevideov3", "scale": 2}, background_tasks)

        self.assertEqual(response["status"], "queued")
        self.assertEqual(response["type"], "upscale")
        self.assertEqual(response["source_job_id"], source_id)
        self.assertEqual(response["upscale_params"]["model"], "realesrgan-animevideov3")
        self.assertEqual(response["upscale_params"]["scale"], 2)

    def test_upscale_rejects_non_completed_source(self) -> None:
        with patch.dict(api._jobs, clear=True):
            api._jobs["running-1"] = {
                "job_id": "running-1", "status": "running", "type": "generate",
                "prompt": "", "params": {}, "output_path": "", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            background_tasks = BackgroundTasks()
            with self.assertRaises(HTTPException) as ctx:
                api.upscale({"source_job_id": "running-1"}, background_tasks)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upscale_rejects_unknown_model(self) -> None:
        with patch.dict(api._jobs, clear=True):
            api._jobs["done-1"] = {
                "job_id": "done-1", "status": "completed", "type": "generate",
                "prompt": "", "params": {}, "output_path": "/out.mp4", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            with patch("app.api.os.path.exists", return_value=True):
                background_tasks = BackgroundTasks()
                with self.assertRaises(HTTPException) as ctx:
                    api.upscale({"source_job_id": "done-1", "model": "nonexistent"}, background_tasks)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upscale_rejects_missing_source_job(self) -> None:
        background_tasks = BackgroundTasks()
        with self.assertRaises(HTTPException) as ctx:
            api.upscale({"source_job_id": "nonexistent"}, background_tasks)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_upscale_rejects_missing_source_file(self) -> None:
        with patch.dict(api._jobs, clear=True):
            api._jobs["done-2"] = {
                "job_id": "done-2", "status": "completed", "type": "generate",
                "prompt": "", "params": {}, "output_path": "/nonexistent.mp4", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            with patch("app.api.os.path.exists", return_value=False):
                background_tasks = BackgroundTasks()
                with self.assertRaises(HTTPException) as ctx:
                    api.upscale({"source_job_id": "done-2"}, background_tasks)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_cancel_queued_job_succeeds(self) -> None:
        with patch.dict(api._jobs, clear=True):
            api._jobs["q1"] = {
                "job_id": "q1", "status": "queued", "type": "generate",
                "prompt": "", "params": {}, "output_path": "", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            result = api.cancel_job("q1", force=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Cancelled by user")

    def test_cancel_running_without_force_returns_warning(self) -> None:
        with patch.dict(api._jobs, clear=True):
            api._jobs["r1"] = {
                "job_id": "r1", "status": "running", "type": "generate",
                "prompt": "", "params": {}, "output_path": "", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
                "_process": None,
            }
            result = api.cancel_job("r1", force=False)

        self.assertTrue(result.get("warning"))

    def test_cancel_completed_job_raises(self) -> None:
        with patch.dict(api._jobs, clear=True):
            api._jobs["c1"] = {
                "job_id": "c1", "status": "completed", "type": "generate",
                "prompt": "", "params": {}, "output_path": "/out.mp4", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            with self.assertRaises(HTTPException) as ctx:
                api.cancel_job("c1", force=False)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_cancel_nonexistent_job_raises(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            api.cancel_job("nonexistent", force=False)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cancel_running_with_force_marks_failed(self) -> None:
        mock_process = unittest.mock.MagicMock()
        mock_process.pid = 12345
        mock_process.wait.return_value = 0

        with patch.dict(api._jobs, clear=True):
            api._jobs["r2"] = {
                "job_id": "r2", "status": "running", "type": "generate",
                "prompt": "", "params": {}, "output_path": "", "download_url": "",
                "created_at": "now", "started_at": None, "finished_at": None,
                "error": None, "source_job_id": None, "upscale_params": None,
                "_process": mock_process,
            }
            result = api.cancel_job("r2", force=True)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "Cancelled by user")
        mock_process.terminate.assert_called_once()

    def test_upscale_and_cancel_queued_job(self) -> None:
        """End-to-end: create source job, upscale it, cancel the upscale."""
        with patch.dict(api._jobs, clear=True):
            source_id = "src-1"
            api._jobs[source_id] = {
                "job_id": source_id, "status": "completed", "type": "generate",
                "prompt": "test", "params": {"width": 448, "height": 224},
                "output_path": "/fake/out.mp4", "download_url": f"/jobs/{source_id}/download",
                "created_at": "now", "started_at": "now", "finished_at": "now",
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            with patch("app.api.os.path.exists", return_value=True):
                background_tasks = BackgroundTasks()
                resp = api.upscale(
                    {"source_job_id": source_id, "model": "realesrgan-animevideov3", "scale": 2},
                    background_tasks,
                )

            upscale_id = resp["job_id"]
            self.assertEqual(resp["type"], "upscale")

            # Cancel the queued upscale job
            result = api.cancel_job(upscale_id, force=False)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"], "Cancelled by user")

    def test_upscale_job_record_has_source_info(self) -> None:
        with patch.dict(api._jobs, clear=True):
            source_id = "src-2"
            api._jobs[source_id] = {
                "job_id": source_id, "status": "completed", "type": "generate",
                "prompt": "hello", "params": {"width": 896, "height": 448},
                "output_path": "/fake/out2.mp4", "download_url": f"/jobs/{source_id}/download",
                "created_at": "now", "started_at": "now", "finished_at": "now",
                "error": None, "source_job_id": None, "upscale_params": None,
            }
            with patch("app.api.os.path.exists", return_value=True):
                background_tasks = BackgroundTasks()
                resp = api.upscale(
                    {"source_job_id": source_id, "model": "seedvr2-3b", "scale": 2},
                    background_tasks,
                )

            job = api.get_job(resp["job_id"])
            self.assertEqual(job["type"], "upscale")
            self.assertEqual(job["source_job_id"], source_id)
            self.assertEqual(job["upscale_params"]["model"], "seedvr2-3b")
            self.assertEqual(job["upscale_params"]["scale"], 2)
            self.assertEqual(job["upscale_params"]["target_width"], 1792)
            self.assertEqual(job["upscale_params"]["target_height"], 896)
