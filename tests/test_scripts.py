from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScriptBoundaryTests(unittest.TestCase):
    def read_script(self, name):
        return (ROOT / "scripts" / name).read_text(encoding="utf-8")

    def test_start_api_does_not_download_or_check_gpu(self):
        script = self.read_script("start-api.sh")
        self.assertIn("python -m app.api_service", script)
        self.assertNotIn("hf download", script)
        self.assertNotIn("nvidia-smi", script)
        self.assertNotIn("check-runtime.sh", script)

    def test_start_worker_checks_runtime_and_starts_worker(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("check-runtime.sh", script)
        self.assertIn("python -m app.worker_service", script)
        self.assertNotIn("hf download", script)

    def test_model_setup_owns_downloads(self):
        script = self.read_script("model-setup.sh")
        self.assertIn("python -m app.models ensure", script)
        self.assertNotIn("hf download", script)
        self.assertNotIn("download-panowan.sh", script)

    def test_start_local_uses_panowan_engine_dir_not_legacy_app_dir(self):
        script = self.read_script("start-local.sh")
        self.assertIn("${PANOWAN_ENGINE_DIR}", script)
        self.assertNotIn("PANOWAN_APP_DIR", script)

    def test_docker_proxy_forwards_compose_interpolation_vars_to_wsl(self):
        script = self.read_script("docker-proxy.sh")
        self.assertIn("docker_proxy_export_wslenv_var", script)
        self.assertIn("for name in TAG MODEL_ROOT PORT APT_MIRROR PYPI_INDEX", script)
        self.assertIn("WSLENV", script)
