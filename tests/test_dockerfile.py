import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DockerfileTests(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    def test_role_targets_exist(self):
        for target in [
            "runtime-base",
            "api-deps",
            "engine-panowan-deps",
            "api",
            "worker-panowan",
            "dev-api",
            "dev-worker-panowan",
        ]:
            self.assertIn(f" AS {target}", self.dockerfile)

    def test_api_target_does_not_copy_panowan_engine(self):
        api_section = self.dockerfile.split("FROM api-deps AS api", 1)[1].split(
            "FROM", 1
        )[0]
        self.assertIn("start-api.sh", api_section)
        self.assertNotIn("third_party/PanoWan", api_section)
        self.assertNotIn("/engines/panowan", api_section)

    def test_worker_target_copies_panowan_engine(self):
        worker_section = self.dockerfile.split(
            "FROM engine-panowan-deps AS worker-panowan", 1
        )[1].split("FROM", 1)[0]
        self.assertIn("/engines/panowan", worker_section)
        self.assertIn("/engines/upscale", worker_section)
        self.assertIn("start-worker.sh", worker_section)

    def test_panowan_build_no_longer_assumes_backend_local_uv_project(self):
        self.assertNotIn("third_party/PanoWan/pyproject.toml", self.dockerfile)
        self.assertNotIn("third_party/PanoWan/uv.lock", self.dockerfile)
        self.assertNotIn("cd /tmp/PanoWan && uv sync", self.dockerfile)
