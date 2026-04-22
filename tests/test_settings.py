import os
import unittest
from unittest.mock import patch

from app.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_load_settings_from_environment(self) -> None:
        env = {
            "PANOWAN_DIR": "/workspace/PanoWan",
            "WAN_MODEL_PATH": "./models/custom-wan",
            "LORA_CHECKPOINT_PATH": "./models/custom-lora.ckpt",
            "DEFAULT_PROMPT": "custom prompt",
            "GENERATION_TIMEOUT_SECONDS": "42",
            "HOST": "127.0.0.1",
            "PORT": "9000",
        }

        with patch.dict(os.environ, env, clear=False):
            loaded = load_settings()

        self.assertEqual(loaded.panowan_dir, "/workspace/PanoWan")
        self.assertEqual(loaded.wan_model_path, "./models/custom-wan")
        self.assertEqual(loaded.lora_checkpoint_path, "./models/custom-lora.ckpt")
        self.assertEqual(loaded.default_prompt, "custom prompt")
        self.assertEqual(loaded.generation_timeout_seconds, 42)
        self.assertEqual(loaded.host, "127.0.0.1")
        self.assertEqual(loaded.port, 9000)
        self.assertEqual(
            loaded.lora_absolute_path,
            "/workspace/PanoWan/models/custom-lora.ckpt",
        )
