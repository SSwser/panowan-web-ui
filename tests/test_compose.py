import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _service_section(compose: str, service_name: str) -> str:
    after = compose.split(f"  {service_name}:", 1)[1]
    return re.split(r"\n(?=(?:  [^\s:#][^\n]*:|[^\s][^\n]*:))", after, maxsplit=1)[0]


class ComposeTests(unittest.TestCase):
    def test_production_compose_uses_split_services(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("api:", compose)
        self.assertIn("worker-panowan:", compose)
        self.assertNotIn("model-setup:", compose)
        self.assertIsNone(re.search(r"^  panowan:\s*$", compose, re.M))

    def test_api_service_has_no_gpu_or_model_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        api_section = _service_section(compose, "api")
        self.assertIn("target: api", api_section)
        self.assertNotIn("gpus:", api_section)
        self.assertNotIn(":/models", api_section)

    def test_worker_service_has_gpu_and_model_mount(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        worker_section = _service_section(compose, "worker-panowan")
        self.assertIn("target: worker-panowan", worker_section)
        self.assertIn("gpus: all", worker_section)
        self.assertIn(":/models", worker_section)
        self.assertNotIn("ENGINE:", worker_section)
        self.assertNotIn("CAPABILITIES:", worker_section)

    def test_worker_service_waits_for_api_health(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        worker_section = _service_section(compose, "worker-panowan")
        api_section = _service_section(compose, "api")
        self.assertIn("depends_on:", worker_section)
        self.assertIn("condition: service_healthy", worker_section)
        self.assertIn("healthcheck:", api_section)


class DevComposeTests(unittest.TestCase):
    def test_dev_compose_has_no_model_setup_service(self):
        compose = (ROOT / "docker-compose-dev.yml").read_text(encoding="utf-8")
        self.assertNotIn("model-setup:", compose)

    def test_dev_worker_panowan_mounts_source_and_models(self):
        compose = (ROOT / "docker-compose-dev.yml").read_text(encoding="utf-8")
        worker_section = _service_section(compose, "worker-panowan")
        self.assertIn("./third_party/PanoWan:/engines/panowan", worker_section)
        self.assertIn("./third_party/Upscale:/engines/upscale", worker_section)
        self.assertIn(":/models", worker_section)

    def test_dev_worker_panowan_does_not_depend_on_one_shot_setup(self):
        compose = (ROOT / "docker-compose-dev.yml").read_text(encoding="utf-8")
        worker_section = _service_section(compose, "worker-panowan")
        self.assertNotIn("service_completed_successfully", worker_section)
        self.assertNotIn("depends_on:", worker_section)

    def test_dev_api_service_mounts_app_sources(self):
        compose = (ROOT / "docker-compose-dev.yml").read_text(encoding="utf-8")
        api_section = _service_section(compose, "api")
        self.assertIn("./app:/app/app", api_section)
        self.assertIn("./scripts:/app/scripts", api_section)
        self.assertNotIn(":/models", api_section)

    def test_dev_compose_declares_shared_uv_cache_volume(self):
        compose = (ROOT / "docker-compose-dev.yml").read_text(encoding="utf-8")
        self.assertIn("panowan-uv-cache:/root/.cache/uv", compose)
        self.assertIn("volumes:\n  panowan-uv-cache:", compose)
