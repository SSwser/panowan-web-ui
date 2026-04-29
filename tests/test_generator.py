import os
import subprocess
import unittest
import unittest.mock
from dataclasses import replace
from unittest.mock import mock_open, patch

from app.generator import (
    JobCancelledError,
    build_runner_payload,
    extract_prompt,
    generate_video,
    resolve_inference_params,
)
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


class ResolveInferenceParamsTests(unittest.TestCase):
    def test_resolves_inference_params_from_preset(self) -> None:
        params = resolve_inference_params({"quality": "draft"})

        self.assertEqual(params["num_inference_steps"], 20)
        self.assertEqual(params["width"], 448)
        self.assertEqual(params["height"], 224)
        self.assertEqual(params["seed"], 0)

    def test_resolves_inference_params_from_stored_job_params(self) -> None:
        params = resolve_inference_params(
            {
                "quality": "draft",
                "params": {
                    "num_inference_steps": 10,
                    "width": 512,
                    "height": 256,
                    "seed": 7,
                    "num_frames": 49,
                },
            }
        )

        self.assertEqual(params["num_inference_steps"], 10)
        self.assertEqual(params["width"], 512)
        self.assertEqual(params["height"], 256)
        self.assertEqual(params["seed"], 7)
        self.assertEqual(params["num_frames"], 49)


class BuildRunnerPayloadTests(unittest.TestCase):
    def test_build_runner_payload_includes_required_fields(self):
        payload = build_runner_payload(
            {
                "id": "j1",
                "prompt": "sky",
                "negative_prompt": "blur",
                "output_path": os.path.join(settings.output_dir, "output_j1.mp4"),
            }
        )
        self.assertEqual(payload["version"], "v1")
        self.assertEqual(payload["task"], "t2v")
        self.assertEqual(payload["prompt"], "sky")
        self.assertEqual(payload["negative_prompt"], "blur")
        self.assertIn("resolution", payload)
        self.assertIn("num_frames", payload)


def _captured_runner_payload(mock_dump):
    """Extract the runner payload dict from the patched json.dump call."""
    assert mock_dump.called, "json.dump was not called"
    return mock_dump.call_args.args[0]


class GenerateVideoTests(unittest.TestCase):
    def test_generate_video_requires_negative_prompt(self) -> None:
        with self.assertRaisesRegex(ValueError, "negative_prompt"):
            generate_video({"id": "job-1", "prompt": "test"})

    @patch("app.generator.json.dump")
    @patch("app.generator.open", new_callable=mock_open)
    @patch("app.generator.os.makedirs")
    @patch("app.generator.os.path.exists", return_value=True)
    @patch("app.generator.os.path.getsize", return_value=11)
    @patch("app.process_runner.subprocess.Popen")
    def test_generates_video_payload(
        self,
        mock_popen,
        mock_getsize,
        mock_exists,
        mock_makedirs,
        mock_open_fn,
        mock_dump,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.return_value = ("ok", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        result = generate_video(
            {"id": "job-1", "prompt": "mountain sunset", "negative_prompt": "blur"}
        )

        self.assertEqual(result["id"], "job-1")
        self.assertEqual(result["prompt"], "mountain sunset")
        self.assertEqual(result["format"], "mp4")
        self.assertEqual(
            result["output_path"],
            os.path.join(settings.output_dir, "output_job-1.mp4"),
        )

        # Assert the new runner.py CLI shape: ["python", "runner.py", "--job", <json>]
        cmd = (
            mock_popen.call_args.kwargs["args"]
            if "args" in mock_popen.call_args.kwargs
            else mock_popen.call_args.args[0]
        )
        self.assertEqual(cmd[:3], ["python", "runner.py", "--job"])
        self.assertTrue(cmd[3].endswith("job-1.json"))

        runner_payload = _captured_runner_payload(mock_dump)
        self.assertEqual(runner_payload["version"], "v1")
        self.assertEqual(runner_payload["task"], "t2v")
        self.assertEqual(runner_payload["prompt"], "mountain sunset")
        self.assertEqual(runner_payload["negative_prompt"], "blur")
        self.assertIn("resolution", runner_payload)
        self.assertIn("num_frames", runner_payload)

    @patch("app.generator.json.dump")
    @patch("app.generator.open", new_callable=mock_open)
    @patch("app.generator.os.makedirs")
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_timeout_kills_process(
        self, mock_popen, mock_makedirs, mock_open_fn, mock_dump
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="test", timeout=10
        )
        mock_process.kill = unittest.mock.MagicMock()
        mock_process.wait = unittest.mock.MagicMock()
        mock_popen.return_value = mock_process

        timeout_settings = replace(settings, generation_timeout_seconds=0)

        with patch("app.generator.settings", timeout_settings):
            with self.assertRaises(TimeoutError):
                generate_video(
                    {
                        "id": "timeout-test",
                        "prompt": "test",
                        "negative_prompt": "blur",
                    }
                )

        mock_process.kill.assert_called_once()
        self.assertGreaterEqual(mock_process.communicate.call_count, 1)

    @patch("app.generator.json.dump")
    @patch("app.generator.open", new_callable=mock_open)
    @patch("app.generator.os.makedirs")
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_kills_process_when_cancelled(
        self,
        mock_popen,
        mock_makedirs,
        mock_open_fn,
        mock_dump,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.side_effect = [("", "")]
        mock_process.kill = unittest.mock.MagicMock()
        mock_popen.return_value = mock_process

        with self.assertRaises(JobCancelledError):
            generate_video(
                {
                    "id": "cancelled-job",
                    "prompt": "test",
                    "negative_prompt": "blur",
                    "_should_cancel": lambda: True,
                }
            )

        mock_process.kill.assert_called_once()

    @patch("app.process_runner.os.killpg", create=True)
    @patch("app.process_runner.os.getpgid", return_value=321, create=True)
    @patch("app.generator.json.dump")
    @patch("app.generator.open", new_callable=mock_open)
    @patch("app.generator.os.makedirs")
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_kills_process_group_on_posix_cancel(
        self,
        mock_popen,
        mock_makedirs,
        mock_open_fn,
        mock_dump,
        mock_getpgid,
        mock_killpg,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.pid = 123
        mock_process.communicate.side_effect = [("", "")]
        mock_process.kill = unittest.mock.MagicMock()
        mock_popen.return_value = mock_process

        with patch("app.generator.os.name", "posix"):
            with self.assertRaises(JobCancelledError):
                generate_video(
                    {
                        "id": "cancelled-job",
                        "prompt": "test",
                        "negative_prompt": "blur",
                        "_should_cancel": lambda: True,
                    }
                )

        mock_getpgid.assert_called_once_with(123)
        mock_killpg.assert_called_once()
        mock_process.kill.assert_not_called()

    @patch("app.generator.json.dump")
    @patch("app.generator.open", new_callable=mock_open)
    @patch("app.generator.os.makedirs")
    @patch("app.generator.os.path.exists", return_value=True)
    @patch("app.generator.os.path.getsize", return_value=11)
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_prefers_persisted_job_params(
        self,
        mock_popen,
        mock_getsize,
        mock_exists,
        mock_makedirs,
        mock_open_fn,
        mock_dump,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.return_value = ("ok", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        generate_video(
            {
                "job_id": "job-queued",
                "prompt": "mountain sunset",
                "negative_prompt": "blur",
                "params": {
                    "num_inference_steps": 10,
                    "width": 896,
                    "height": 448,
                    "seed": 3,
                    "num_frames": 81,
                },
            }
        )

        runner_payload = _captured_runner_payload(mock_dump)
        self.assertEqual(runner_payload["resolution"]["width"], 896)
        self.assertEqual(runner_payload["resolution"]["height"], 448)
        self.assertEqual(runner_payload["num_frames"], 81)
        self.assertEqual(runner_payload["seed"], 3)
        self.assertEqual(runner_payload["num_inference_steps"], 10)

    @patch("app.generator.json.dump")
    @patch("app.generator.open", new_callable=mock_open)
    @patch("app.generator.os.makedirs")
    @patch("app.generator.os.path.exists", return_value=True)
    @patch("app.generator.os.path.getsize", return_value=11)
    @patch("app.process_runner.subprocess.Popen")
    def test_generate_video_writes_i2v_runner_payload(
        self,
        mock_popen,
        mock_getsize,
        mock_exists,
        mock_makedirs,
        mock_open_fn,
        mock_dump,
    ):
        mock_process = unittest.mock.MagicMock()
        mock_process.communicate.return_value = ("ok", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        result = generate_video(
            {
                "id": "job-i2v",
                "task": "i2v",
                "prompt": "pan right",
                "negative_prompt": "blur",
                "input_image_path": "/tmp/frame0.png",
                "denoising_strength": 0.7,
                "output_path": os.path.join(settings.output_dir, "output_job-i2v.mp4"),
            }
        )

        self.assertEqual(result["id"], "job-i2v")
        self.assertTrue(mock_popen.called)
        runner_payload = _captured_runner_payload(mock_dump)
        self.assertEqual(runner_payload["task"], "i2v")
        self.assertEqual(runner_payload["input_image_path"], "/tmp/frame0.png")
        self.assertEqual(runner_payload["denoising_strength"], 0.7)
