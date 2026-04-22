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
