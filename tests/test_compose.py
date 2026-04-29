from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ComposeTests(unittest.TestCase):
    def test_production_compose_uses_split_services(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("api:", compose)
        self.assertIn("worker-panowan:", compose)
        self.assertNotIn("model-setup:", compose)
        self.assertIsNone(re.search(r"^  panowan:\s*$", compose, re.M))

    def test_api_service_has_no_gpu_or_model_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        api_section = compose.split("  api:", 1)[1].split("  worker-panowan:", 1)[0]
        self.assertIn("target: api", api_section)
        self.assertNotIn("gpus:", api_section)
        self.assertNotIn(":/models", api_section)

    def test_worker_service_has_gpu_and_model_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        worker_section = compose.split("  worker-panowan:", 1)[1]
        self.assertIn("target: worker-panowan", worker_section)
        self.assertIn("gpus: all", worker_section)
        self.assertIn(":/models", worker_section)
        self.assertNotIn("ENGINE:", worker_section)
        self.assertNotIn("CAPABILITIES:", worker_section)

    def test_worker_service_waits_for_api_health(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        worker_section = compose.split("  worker-panowan:", 1)[1]
        api_section = compose.split("  api:", 1)[1].split("  worker-panowan:", 1)[0]
        self.assertIn("depends_on:", worker_section)
        self.assertIn("condition: service_healthy", worker_section)
        self.assertIn("healthcheck:", api_section)
