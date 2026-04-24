import os
import unittest
from unittest import mock
from unittest.mock import patch

from app.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_load_settings_from_environment(self) -> None:
        env = {
            "PANOWAN_ENGINE_DIR": "/workspace/PanoWan",
            "MODEL_ROOT": "/workspace/models",
            "WAN_MODEL_PATH": "/workspace/models/custom-wan",
            "LORA_CHECKPOINT_PATH": "/models/custom-lora.ckpt",
            "DEFAULT_PROMPT": "custom prompt",
            "GENERATION_TIMEOUT_SECONDS": "42",
            "HOST": "127.0.0.1",
            "PORT": "9000",
        }

        with patch.dict(os.environ, env, clear=False):
            loaded = load_settings()

        self.assertEqual(loaded.panowan_engine_dir, "/workspace/PanoWan")
        self.assertEqual(loaded.panowan_app_dir, "/workspace/PanoWan")
        self.assertEqual(loaded.wan_model_path, "/workspace/models/custom-wan")
        self.assertEqual(loaded.lora_checkpoint_path, "/models/custom-lora.ckpt")
        self.assertEqual(loaded.default_prompt, "custom prompt")
        self.assertEqual(loaded.generation_timeout_seconds, 42)
        self.assertEqual(loaded.host, "127.0.0.1")
        self.assertEqual(loaded.port, 9000)
        self.assertEqual(
            loaded.lora_absolute_path,
            "/models/custom-lora.ckpt",
        )

    def test_load_settings_includes_upscale_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            loaded = load_settings()
        self.assertEqual(loaded.upscale_model_dir, "/models/upscale")
        self.assertEqual(loaded.upscale_output_dir, "/app/runtime/outputs")
        self.assertEqual(loaded.upscale_timeout_seconds, 1800)

    def test_load_settings_upscale_from_environment(self) -> None:
        env = {
            "UPSCALE_MODEL_DIR": "/custom/models",
            "UPSCALE_OUTPUT_DIR": "/custom/outputs",
            "UPSCALE_TIMEOUT_SECONDS": "900",
        }
        with patch.dict(os.environ, env, clear=False):
            loaded = load_settings()
        self.assertEqual(loaded.upscale_model_dir, "/custom/models")
        self.assertEqual(loaded.upscale_output_dir, "/custom/outputs")
        self.assertEqual(loaded.upscale_timeout_seconds, 900)

    def test_container_path_join_uses_posix_separators(self):
        from app.paths import container_join

        self.assertEqual(
            container_join("/engines/panowan", "models/PanoWan/latest-lora.ckpt"),
            "/engines/panowan/models/PanoWan/latest-lora.ckpt",
        )

    def test_container_path_join_handles_root_base(self):
        from app.paths import container_join

        self.assertEqual(container_join("/", "models/foo"), "/models/foo")

    def test_load_settings_uses_model_root_and_engine_dir(self):
        env = {
            "PANOWAN_ENGINE_DIR": "/engines/panowan",
            "MODEL_ROOT": "/models",
            "WAN_MODEL_PATH": "/models/Wan-AI/Wan2.1-T2V-1.3B",
            "LORA_CHECKPOINT_PATH": "/models/PanoWan/latest-lora.ckpt",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            loaded = load_settings()

        self.assertEqual(loaded.panowan_engine_dir, "/engines/panowan")
        self.assertEqual(loaded.model_root, "/models")
        self.assertEqual(
            loaded.wan_diffusion_absolute_path,
            "/models/Wan-AI/Wan2.1-T2V-1.3B/diffusion_pytorch_model.safetensors",
        )
        self.assertEqual(
            loaded.lora_absolute_path,
            "/models/PanoWan/latest-lora.ckpt",
        )
