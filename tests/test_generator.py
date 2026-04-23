import os
import unittest
from types import SimpleNamespace
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
    @patch("app.generator.subprocess.run")
    def test_generates_video_payload(
        self,
        mock_run,
        mock_getsize,
        mock_exists,
        mock_makedirs,
    ) -> None:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")

        result = generate_video({"id": "job-1", "prompt": "mountain sunset"})

        self.assertEqual(result["id"], "job-1")
        self.assertEqual(result["prompt"], "mountain sunset")
        self.assertEqual(result["format"], "mp4")
        self.assertEqual(
            result["output_path"],
            os.path.join(settings.output_dir, "output_job-1.mp4"),
        )
        mock_run.assert_called_once_with(
            [
                "uv",
                "run",
                "panowan-test",
                "--wan-model-path",
                settings.wan_model_path,
                "--lora-checkpoint-path",
                settings.lora_checkpoint_path,
                "--output-path",
                os.path.join(settings.output_dir, "output_job-1.mp4"),
                "--prompt",
                "mountain sunset",
                "--num-inference-steps",
                str(settings.default_num_inference_steps),
                "--width",
                str(settings.default_width),
                "--height",
                str(settings.default_height),
                "--seed",
                "0",
            ],
            cwd=settings.panowan_app_dir,
            capture_output=True,
            text=True,
            timeout=settings.generation_timeout_seconds,
        )
        mock_getsize.assert_called_once_with(
            os.path.join(settings.output_dir, "output_job-1.mp4")
        )
        mock_makedirs.assert_called_once_with(settings.output_dir, exist_ok=True)
        self.assertTrue(mock_exists.called)
