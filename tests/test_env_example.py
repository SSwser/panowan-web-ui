from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EnvExampleTests(unittest.TestCase):
    def setUp(self):
        self.env = (ROOT / ".env.example").read_text(encoding="utf-8")

    def test_env_example_keeps_operator_facing_runtime_inputs(self):
        for key in [
            "HOST=",
            "PORT=",
            "JOB_BACKEND=",
            "WORKER_POLL_INTERVAL_SECONDS=",
            "WORKER_STALE_SECONDS=",
            "MAX_CONCURRENT_JOBS=",
            "UPSCALE_TIMEOUT_SECONDS=",
        ]:
            self.assertIn(key, self.env)

    def test_env_example_omits_derived_runtime_paths(self):
        for key in [
            "RUNTIME_DIR",
            "WORKER_STORE_PATH",
            "PANOWAN_ENGINE_DIR",
            "WAN_MODEL_PATH",
            "LORA_CHECKPOINT_PATH",
            "UPSCALE_ENGINE_DIR",
            "UPSCALE_WEIGHTS_DIR",
            "UPSCALE_OUTPUT_DIR",
        ]:
            self.assertIsNone(
                re.search(rf"(?m)^[ \t]*{re.escape(key)}=", self.env),
                key,
            )

    def test_legacy_panowan_app_dir_is_not_primary_configuration(self):
        self.assertNotIn("PANOWAN_APP_DIR=", self.env)
