from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnvExampleTests(unittest.TestCase):
    def setUp(self):
        self.env = (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_product_runtime_variables_exist(self):
        for key in [
            "RUNTIME_DIR=",
            "JOB_BACKEND=",
            "ENGINE=",
            "CAPABILITIES=",
            "MODEL_ROOT=",
            "PANOWAN_ENGINE_DIR=",
            "WAN_MODEL_PATH=",
            "LORA_CHECKPOINT_PATH=",
            "UPSCALE_MODEL_DIR=",
        ]:
            self.assertIn(key, self.env)

    def test_legacy_panowan_app_dir_is_not_primary_configuration(self):
        self.assertNotIn("PANOWAN_APP_DIR=", self.env)
