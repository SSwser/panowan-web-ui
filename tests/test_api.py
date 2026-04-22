import importlib.util
import unittest
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from fastapi import BackgroundTasks, HTTPException
    from fastapi.responses import FileResponse
    from app import api


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ApiTests(unittest.TestCase):
    def test_healthcheck_reports_path_status(self) -> None:
        path_exists = {
            api.settings.panowan_dir: True,
            api.settings.lora_absolute_path: False,
        }

        with patch("app.api.os.path.exists", side_effect=path_exists.get), patch(
            "app.api._path_has_content", return_value=False
        ):
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
        with patch("app.api.os.path.exists", return_value=True), patch(
            "app.api._path_has_content", return_value=True
        ):
            result = api.healthcheck()

        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["service_started"])
        self.assertTrue(result["model_ready"])
        self.assertTrue(result["wan_model_exists"])
        self.assertTrue(result["lora_exists"])

    def test_generate_maps_timeout_to_http_504(self) -> None:
        with patch("app.api.generate_video", side_effect=TimeoutError("too slow")):
            with self.assertRaises(HTTPException) as exc_info:
                api.generate({"prompt": "test"}, BackgroundTasks())

        self.assertEqual(exc_info.exception.status_code, 504)
        self.assertEqual(exc_info.exception.detail, "too slow")

    def test_generate_returns_mp4_file_response(self) -> None:
        with patch(
            "app.api.generate_video",
            return_value={
                "id": "job-1",
                "prompt": "test",
                "format": "mp4",
                "output_path": "/tmp/output_job-1.mp4",
            },
        ):
            response = api.generate({"prompt": "test"}, BackgroundTasks())

        self.assertIsInstance(response, FileResponse)
        self.assertEqual(response.path, "/tmp/output_job-1.mp4")
        self.assertEqual(response.media_type, "video/mp4")
        self.assertEqual(response.headers["x-job-id"], "job-1")
