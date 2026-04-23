import os
import subprocess
import unittest
import unittest.mock
from unittest.mock import patch

from app.generator import extract_prompt, generate_video, resolve_inference_params
from app.settings import settings


class ExtractPromptTests(unittest.TestCase):
    def test_prefers_top_level_prompt(self) -> None:
        payload = {"prompt": "top-level prompt", "input": {"prompt": "nested"}}

        self.assertEqual(extract_prompt(payload), "top-level prompt")

    def test_falls_back_to_nested_prompt(self) -> None:
        payload = {"input": {"prompt": "nested prompt"}}

        self.assertEqual(extract_prompt(payload), "nested prompt")

    def test_uses_default_prompt_when_missing(self) -> None:
        self.assertEqual(extract_prompt({}), settings.default_prompt)


class GenerateVideoTests(unittest.TestCase):
    def test_resolves_inference_params_from_preset(self) -> None:
        params = resolve_inference_params({"quality": "draft"})

        self.assertEqual(params["num_inference_steps"], 20)
        self.assertEqual(params["width"], 448)
        self.assertEqual(params["height"], 224)
        self.assertEqual(params["seed"], 0)
        self.assertEqual(params["negative_prompt"], "")

    @patch("app.generator.os.makedirs")
    @patch("app.generator.os.path.exists", return_value=True)
    @patch("app.generator.os.path.getsize", return_value=11)
    @patch("app.generator.subprocess.Popen")
    def test_generates_video_payload(
        self,
        mock_popen,
        mock_getsize,
        mock_exists,
        mock_makedirs,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.return_value = ("ok", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        result = generate_video({"id": "job-1", "prompt": "mountain sunset"})

        self.assertEqual(result["id"], "job-1")
        self.assertEqual(result["prompt"], "mountain sunset")
        self.assertEqual(result["format"], "mp4")
        self.assertEqual(
            result["output_path"],
            os.path.join(settings.output_dir, "output_job-1.mp4"),
        )
        mock_popen.assert_called_once()
        mock_getsize.assert_called_once_with(
            os.path.join(settings.output_dir, "output_job-1.mp4")
        )
        mock_makedirs.assert_called_once_with(settings.output_dir, exist_ok=True)
        self.assertTrue(mock_exists.called)

    @patch("app.generator.os.makedirs")
    @patch("app.generator.subprocess.Popen")
    def test_generate_video_timeout_kills_process(self, mock_popen, mock_makedirs):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=10)
        mock_process.kill = unittest.mock.MagicMock()
        mock_process.wait = unittest.mock.MagicMock()
        mock_popen.return_value = mock_process

        with self.assertRaises(TimeoutError):
            generate_video({"id": "timeout-test", "prompt": "test"})

        mock_process.kill.assert_called_once()
        mock_process.wait.assert_called_once()
