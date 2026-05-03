import unittest
from pathlib import Path

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

    def test_realesrgan_sources_own_generated_vendor_boundary(self):
        backend_root = ROOT / "third_party" / "Upscale" / "realesrgan"
        self.assertFalse((ROOT / "third_party" / "Upscale" / ".gitignore").exists())
        backend_gitignore = (backend_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("vendor/", backend_gitignore)
        self.assertIn(".tmp/", backend_gitignore)
        self.assertIn("build/", backend_gitignore)
        self.assertIn("__pycache__/", backend_gitignore)

        sources_root = backend_root / "sources"
        self.assertTrue((sources_root / "__main__.py").exists())
        self.assertTrue((sources_root / "inference_realesrgan_video.py").exists())
        self.assertTrue((sources_root / "realesrgan" / "utils.py").exists())
        self.assertFalse((backend_root / "overlay").exists())

    def test_realesrgan_runner_delegates_to_materialized_vendor_entrypoint(self):
        runner = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "runner.py"
        ).read_text(encoding="utf-8")
        self.assertIn('vendor_main = backend_root / "vendor" / "__main__.py"', runner)
        self.assertIn("runpy.run_path", runner)
        self.assertIn("sys.argv", runner)

    def test_realesrgan_vendor_entrypoint_uses_flat_layout_without_runtime_pip(self):
        # The generated runtime bundle is the contract: a flat ``vendor/``
        # directory whose ``__main__.py`` prepends itself to ``sys.path`` and
        # delegates to the trimmed ``inference_realesrgan_video.main`` — no
        # runtime pip, no environment variable discovery, no fallback paths.
        entry = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "sources" / "__main__.py"
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

    def test_realesrgan_runtime_sources_do_not_require_basicsr_package(self):
        requirements = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "requirements.txt"
        ).read_text(encoding="utf-8")
        sources = ROOT / "third_party" / "Upscale" / "realesrgan" / "sources"
        runner = (sources / "inference_realesrgan_video.py").read_text(encoding="utf-8")
        utils = (sources / "realesrgan" / "utils.py").read_text(encoding="utf-8")
        arch = (sources / "realesrgan" / "srvgg_arch.py").read_text(encoding="utf-8")
        self.assertNotIn("basicsr", requirements)
        self.assertNotIn("from basicsr", runner)
        self.assertNotIn("gfpgan", runner)
        self.assertNotIn("load_file_from_url", utils)
        self.assertNotIn("ARCH_REGISTRY", arch)

    def test_realesrgan_runtime_source_package_inits_are_trimmed(self):
        sources_pkg = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "sources" / "realesrgan"
        )
        package_init = (sources_pkg / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("from .utils import RealESRGANer", package_init)
        self.assertIn("from .srvgg_arch import SRVGGNetCompact", package_init)
        self.assertNotIn("from .data", package_init)
        self.assertNotIn("from .models", package_init)
        self.assertNotIn("from .version", package_init)
        self.assertFalse((sources_pkg / "archs").exists())

    def test_realesrgan_runtime_source_only_exposes_supported_cli_surface(self):
        runner = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "sources"
            / "inference_realesrgan_video.py"
        ).read_text(encoding="utf-8")
        self.assertIn('default="realesr-animevideov3"', runner)
        self.assertNotIn("RealESRGAN_x4plus", runner)
        self.assertNotIn("--denoise_strength", runner)
        self.assertNotIn("--alpha_upsampler", runner)
        self.assertNotIn('"--ext",', runner)
        self.assertNotIn("GFPGANer(", runner)
        self.assertIn("--face_enhance", runner)
        self.assertIn("raise RuntimeError", runner)
        self.assertIn("face_enhance is unsupported in generated runtime bundle", runner)
        self.assertNotIn('print("Error", error)', runner)
        self.assertIn("torch.cuda.is_available()", runner)
        self.assertNotIn("torch.cuda.synchronize(device)", runner)
        self.assertIn("torch.cuda.synchronize()", runner)
        self.assertNotIn("turned this option off for you", runner)
        self.assertNotIn("GFPGAN is not installed; disabling face enhancement.", runner)
        self.assertNotIn("https://github.com/TencentARC/GFPGAN", runner)
        self.assertIn("CUDA out of memory", runner)
        self.assertIn("failed on frame", runner)
        self.assertIn("unsupported in generated runtime bundle", runner)
        self.assertIn("nb_frames", runner)
        self.assertIn('if not ret["nb_frames"]:', runner)
        self.assertIn("count_frames(", runner)
        self.assertNotIn('eval(video_streams[0]["avg_frame_rate"])', runner)

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

    def test_env_sh_does_not_define_duplicated_runtime_path_defaults(self):
        script = self.read_script("lib/env.sh")
        self.assertNotIn('export PANOWAN_ENGINE_DIR="${PANOWAN_ENGINE_DIR:-', script)
        self.assertNotIn('export WAN_MODEL_PATH="${WAN_MODEL_PATH:-', script)
        self.assertNotIn(
            'export LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-', script
        )
        self.assertNotIn('export OUTPUT_DIR="${OUTPUT_DIR:-', script)
        self.assertNotIn('export JOB_STORE_PATH="${JOB_STORE_PATH:-', script)
        self.assertNotIn('export WORKER_STORE_PATH="${WORKER_STORE_PATH:-', script)
        self.assertNotIn('export UPSCALE_ENGINE_DIR="${UPSCALE_ENGINE_DIR:-', script)
        self.assertNotIn('export UPSCALE_OUTPUT_DIR="${UPSCALE_OUTPUT_DIR:-', script)

    def test_env_sh_exports_python_derived_settings(self):
        script = self.read_script("lib/env.sh")
        self.assertIn("from app.settings import load_settings", script)
        self.assertIn("panowan_export_python_settings", script)
        self.assertIn('"WAN_MODEL_PATH": settings.wan_model_path', script)
        self.assertIn('"OUTPUT_DIR": settings.output_dir', script)
        self.assertIn('"UPSCALE_OUTPUT_DIR": settings.upscale_output_dir', script)

    def test_start_worker_supports_vmtouch(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("VMTOUCH_MODELS", script)

    def test_docker_proxy_forwards_compose_interpolation_vars_to_wsl(self):
        script = self.read_script("docker-proxy.sh")
        self.assertIn("docker_proxy_export_wslenv_var", script)
        # MODEL_ROOT is forwarded with /p so WSL converts the Windows path;
        # remaining vars are forwarded without a modifier.
        self.assertIn('docker_proxy_export_wslenv_var "MODEL_ROOT" "/p"', script)
        self.assertIn("for name in TAG PORT FRONTEND_PORT APT_MIRROR PYPI_INDEX", script)
        self.assertIn("WSLENV", script)
