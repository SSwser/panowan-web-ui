import os
import unittest

from app.generator import (
    build_runner_payload,
    extract_prompt,
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

    def test_defaults_to_draft_quality_when_unspecified(self) -> None:
        params = resolve_inference_params({})

        self.assertEqual(params["num_inference_steps"], 20)
        self.assertEqual(params["width"], 448)
        self.assertEqual(params["height"], 224)
        self.assertEqual(params["seed"], 0)
        self.assertEqual(params["num_frames"], 81)


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

    def test_build_runner_payload_prefers_persisted_job_params(self) -> None:
        payload = build_runner_payload(
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

        self.assertEqual(payload["resolution"]["width"], 896)
        self.assertEqual(payload["resolution"]["height"], 448)
        self.assertEqual(payload["num_frames"], 81)
        self.assertEqual(payload["seed"], 3)
        self.assertEqual(payload["num_inference_steps"], 10)

    def test_build_runner_payload_writes_i2v_fields(self) -> None:
        payload = build_runner_payload(
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

        self.assertEqual(payload["task"], "i2v")
        self.assertEqual(payload["input_image_path"], "/tmp/frame0.png")
        self.assertEqual(payload["denoising_strength"], 0.7)

    def test_build_runner_payload_defaults_missing_negative_prompt(self) -> None:
        payload = build_runner_payload({"id": "job-1", "prompt": "test"})
        self.assertEqual(payload["negative_prompt"], "")

    def test_build_runner_payload_requires_i2v_denoising_strength(self) -> None:
        with self.assertRaisesRegex(ValueError, "denoising_strength is required"):
            build_runner_payload(
                {
                    "id": "job-i2v",
                    "task": "i2v",
                    "prompt": "pan right",
                    "input_image_path": "/tmp/frame0.png",
                }
            )

    def test_build_runner_payload_rejects_non_numeric_i2v_denoising_strength(self) -> None:
        with self.assertRaisesRegex(ValueError, "denoising_strength must be a number"):
            build_runner_payload(
                {
                    "id": "job-i2v",
                    "task": "i2v",
                    "prompt": "pan right",
                    "input_image_path": "/tmp/frame0.png",
                    "denoising_strength": "0.7",
                }
            )

    def test_build_runner_payload_keeps_i2v_shape_for_future_runtime_support(self) -> None:
        payload = build_runner_payload(
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
        self.assertEqual(payload["task"], "i2v")
        self.assertEqual(payload["input_image_path"], "/tmp/frame0.png")
        self.assertEqual(payload["denoising_strength"], 0.7)
        self.assertEqual(payload["prompt"], "pan right")
        self.assertEqual(payload["negative_prompt"], "blur")
        self.assertIn("resolution", payload)
        self.assertIn("num_frames", payload)


if __name__ == "__main__":
    unittest.main()
