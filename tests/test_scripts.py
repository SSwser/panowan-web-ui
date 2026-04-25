from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScriptBoundaryTests(unittest.TestCase):
    def read_script(self, name):
        return (ROOT / "scripts" / name).read_text(encoding="utf-8")

    def test_dockerfile_builds_realesrgan_backend_venv(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("AS upscale-realesrgan-deps", dockerfile)
        self.assertIn("/opt/venvs/upscale-realesrgan", dockerfile)
        self.assertIn(
            "third_party/Upscale/realesrgan/requirements.txt",
            dockerfile,
        )
        self.assertIn(
            "COPY --from=upscale-realesrgan-deps /opt/venvs/upscale-realesrgan /opt/venvs/upscale-realesrgan",
            dockerfile,
        )

    def test_dockerfile_installs_ffmpeg_system_command(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ffmpeg", dockerfile)

    def test_realesrgan_vendor_entrypoint_uses_flat_layout_without_runtime_pip(self):
        # The vendored runtime is the contract: a flat ``vendor/`` directory
        # whose ``__main__.py`` prepends itself to ``sys.path`` and delegates
        # to the trimmed ``inference_realesrgan_video.main`` — no runtime pip,
        # no environment variable discovery, no fallback paths.
        entry = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "vendor" / "__main__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Path(__file__).resolve().parent", entry)
        self.assertIn("sys.path.insert", entry)
        self.assertIn("import inference_realesrgan_video", entry)
        self.assertNotIn("pip.main", entry)
        self.assertNotIn("pip install", entry)
        # The legacy adapter and nested ``vendor/Real-ESRGAN`` tree must be
        # gone so they cannot drift back in.
        self.assertFalse(
            (ROOT / "third_party" / "Upscale" / "realesrgan" / "adapter.py").exists()
        )
        self.assertFalse(
            (
                ROOT
                / "third_party"
                / "Upscale"
                / "realesrgan"
                / "vendor"
                / "Real-ESRGAN"
            ).exists()
        )

    def test_realesrgan_runtime_bundle_does_not_require_basicsr_package(self):
        requirements = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "requirements.txt"
        ).read_text(encoding="utf-8")
        vendor = ROOT / "third_party" / "Upscale" / "realesrgan" / "vendor"
        runner = (vendor / "inference_realesrgan_video.py").read_text(encoding="utf-8")
        utils = (vendor / "realesrgan" / "utils.py").read_text(encoding="utf-8")
        arch = (vendor / "realesrgan" / "archs" / "srvgg_arch.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("basicsr", requirements)
        self.assertNotIn("from basicsr", runner)
        self.assertIn("GFPGANer = None", runner)
        self.assertNotIn("load_file_from_url", utils)
        self.assertNotIn("ARCH_REGISTRY", arch)

    def test_realesrgan_runtime_package_inits_are_trimmed(self):
        vendor_pkg = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "vendor" / "realesrgan"
        )
        package_init = (vendor_pkg / "__init__.py").read_text(encoding="utf-8")
        arch_init = (vendor_pkg / "archs" / "__init__.py").read_text(encoding="utf-8")
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

    def test_check_runtime_invokes_backends_verify(self):
        script = self.read_script("check-runtime.sh")
        self.assertIn("python -m app.backends verify", script)

    def test_start_worker_supports_vmtouch(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("VMTOUCH_MODELS", script)

    def test_docker_proxy_forwards_compose_interpolation_vars_to_wsl(self):
        script = self.read_script("docker-proxy.sh")
        self.assertIn("docker_proxy_export_wslenv_var", script)
        self.assertIn("for name in TAG MODEL_ROOT PORT APT_MIRROR PYPI_INDEX", script)
        self.assertIn("WSLENV", script)
