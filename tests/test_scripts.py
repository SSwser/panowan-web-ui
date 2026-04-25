from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScriptBoundaryTests(unittest.TestCase):
    def read_script(self, name):
        return (ROOT / "scripts" / name).read_text(encoding="utf-8")

    def test_realesrgan_adapter_uses_vendored_snapshot_without_runtime_pip(self):
        adapter = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "adapter.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"vendor" / "Real-ESRGAN"', adapter)
        self.assertIn('"inference_realesrgan_video.py"', adapter)
        self.assertIn("sys.path.insert", adapter)
        self.assertNotIn("pip.main", adapter)
        self.assertNotIn("pip install", adapter)

    def test_realesrgan_runtime_bundle_does_not_require_basicsr_package(self):
        requirements = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "requirements.txt"
        ).read_text(encoding="utf-8")
        runner = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "Real-ESRGAN"
            / "inference_realesrgan_video.py"
        ).read_text(encoding="utf-8")
        utils = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "Real-ESRGAN"
            / "realesrgan"
            / "utils.py"
        ).read_text(encoding="utf-8")
        arch = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "Real-ESRGAN"
            / "realesrgan"
            / "archs"
            / "srvgg_arch.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("basicsr", requirements)
        self.assertNotIn("from basicsr", runner)
        self.assertIn("GFPGANer = None", runner)
        self.assertNotIn("load_file_from_url", utils)
        self.assertNotIn("ARCH_REGISTRY", arch)

    def test_realesrgan_runtime_package_inits_are_trimmed(self):
        package_init = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "Real-ESRGAN"
            / "realesrgan"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        arch_init = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "Real-ESRGAN"
            / "realesrgan"
            / "archs"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from .utils import RealESRGANer", package_init)
        self.assertNotIn("from .data", package_init)
        self.assertNotIn("from .models", package_init)
        self.assertNotIn("from .version", package_init)
        self.assertEqual(
            arch_init.strip(),
            'from .srvgg_arch import SRVGGNetCompact\n\n__all__ = ["SRVGGNetCompact"]',
        )

    def test_realesrgan_runner_only_exposes_supported_cli_surface(self):
        runner = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "Real-ESRGAN"
            / "inference_realesrgan_video.py"
        ).read_text(encoding="utf-8")
        self.assertIn('default="realesr-animevideov3"', runner)
        self.assertNotIn("RealESRGAN_x4plus", runner)
        self.assertNotIn("--denoise_strength", runner)
        self.assertNotIn("--alpha_upsampler", runner)
        self.assertNotIn('"--ext",', runner)

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

    def test_start_worker_supports_vmtouch(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("VMTOUCH_MODELS", script)

    def test_docker_proxy_forwards_compose_interpolation_vars_to_wsl(self):
        script = self.read_script("docker-proxy.sh")
        self.assertIn("docker_proxy_export_wslenv_var", script)
        self.assertIn("for name in TAG MODEL_ROOT PORT APT_MIRROR PYPI_INDEX", script)
        self.assertIn("WSLENV", script)
