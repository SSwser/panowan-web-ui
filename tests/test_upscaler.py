import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.upscaler import (
    UPSCALE_BACKENDS,
    RealBasicVSRBackend,
    UpscaleCancelledError,
    RealESRGANBackend,
    SeedVR2Backend,
    get_available_upscale_backends,
    upscale_video,
)


class UpscalerRegistryTests(unittest.TestCase):
    def test_registry_contains_expected_backends(self) -> None:
        self.assertIn("realesrgan-animevideov3", UPSCALE_BACKENDS)
        self.assertIn("realbasicvsr", UPSCALE_BACKENDS)
        self.assertIn("seedvr2-3b", UPSCALE_BACKENDS)

    def test_all_backends_have_required_fields(self) -> None:
        for name, backend in UPSCALE_BACKENDS.items():
            self.assertEqual(backend.name, name)
            self.assertIsInstance(backend.display_name, str)
            self.assertTrue(len(backend.display_name) > 0)
            self.assertIsInstance(backend.default_scale, int)
            self.assertGreaterEqual(backend.default_scale, 2)
            self.assertIsInstance(backend.max_scale, int)
            self.assertGreaterEqual(backend.max_scale, backend.default_scale)


class UpscalerAvailabilityTests(unittest.TestCase):
    backend_name = "realesrgan-animevideov3"

    def _write_relative_file(
        self, root_dir: str, relative_path: str, contents: str = "x"
    ) -> None:
        file_path = Path(root_dir, *relative_path.split("/"))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(contents)

    def _materialize_backend_assets(
        self, engine_dir: str, weights_dir: str | None = None
    ) -> None:
        backend = UPSCALE_BACKENDS[self.backend_name]
        for relative_path in backend.assets.engine_files:
            self._write_relative_file(engine_dir, relative_path)
        if weights_dir is None:
            return
        for relative_path in backend.assets.weight_files:
            self._write_relative_file(weights_dir, relative_path)

    def test_registered_backends_declare_assets(self) -> None:
        for backend in UPSCALE_BACKENDS.values():
            self.assertTrue(backend.assets.engine_files)
            self.assertIsInstance(backend.assets.weight_files, tuple)
            self.assertIsInstance(backend.assets.required_commands, tuple)

    def test_registered_backends_declare_runtime_module_tuple(self) -> None:
        for backend in UPSCALE_BACKENDS.values():
            self.assertIsInstance(backend.assets.required_python_modules, tuple)

    def test_realesrgan_declares_backend_runtime_python(self) -> None:
        backend = UPSCALE_BACKENDS["realesrgan-animevideov3"]
        self.assertEqual(backend.assets.runtime_python, backend.runtime_python)
        self.assertEqual(backend.runtime_python, "/opt/venvs/upscale-realesrgan/bin/python")
        self.assertIn("cv2", backend.assets.required_python_modules)
        self.assertIn("ffmpeg", backend.assets.required_python_modules)
        self.assertIn("tqdm", backend.assets.required_python_modules)

    def test_backend_unavailable_when_engine_file_missing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            backend = UPSCALE_BACKENDS[self.backend_name]
            for relative_path in backend.assets.weight_files:
                self._write_relative_file(weights_dir, relative_path)

            available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)

    def test_backend_unavailable_when_runner_missing_even_if_vendor_exists(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            real_exists = os.path.exists
            self._materialize_backend_assets(engine_dir, weights_dir)
            runner_path = Path(engine_dir, "realesrgan", "runner.py")
            runner_path.unlink()

            with (
                patch("app.upscaler.shutil.which", return_value="ffmpeg"),
                patch("app.upscaler.os.path.exists") as mock_exists,
                patch("app.upscaler.subprocess.run") as mock_run,
            ):
                mock_run.return_value = SimpleNamespace(returncode=0)

                def exists(path: str) -> bool:
                    if path == UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python:
                        return True
                    return real_exists(path)

                mock_exists.side_effect = exists
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)

    def test_backend_unavailable_when_weight_file_missing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            self._materialize_backend_assets(engine_dir)

            available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)

    def test_backend_available_when_assets_exist(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            real_exists = os.path.exists
            self._materialize_backend_assets(engine_dir, weights_dir)

            with (
                patch("app.upscaler.shutil.which", return_value="ffmpeg"),
                patch("app.upscaler.os.path.exists") as mock_exists,
                patch("app.upscaler.subprocess.run") as mock_run,
            ):
                mock_run.return_value = SimpleNamespace(returncode=0)

                def exists(path: str) -> bool:
                    if path == UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python:
                        return True
                    return real_exists(path)

                mock_exists.side_effect = exists
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertIn("realesrgan-animevideov3", available)

    def test_backend_unavailable_when_runtime_python_missing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            real_exists = os.path.exists
            self._materialize_backend_assets(engine_dir, weights_dir)

            with (
                patch("app.upscaler.shutil.which", return_value="ffmpeg"),
                patch("app.upscaler.os.path.exists") as mock_exists,
            ):

                def exists(path: str) -> bool:
                    if path == UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python:
                        return False
                    return real_exists(path)

                mock_exists.side_effect = exists
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)

    def test_backend_unavailable_when_runtime_probe_fails(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            real_exists = os.path.exists
            self._materialize_backend_assets(engine_dir, weights_dir)

            with (
                patch("app.upscaler.shutil.which", return_value="ffmpeg"),
                patch("app.upscaler.os.path.exists") as mock_exists,
                patch("app.upscaler.subprocess.run") as mock_run,
            ):
                mock_run.return_value = SimpleNamespace(returncode=1)

                def exists(path: str) -> bool:
                    if path == UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python:
                        return True
                    return real_exists(path)

                mock_exists.side_effect = exists
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("realesrgan-animevideov3", available)
        mock_run.assert_called_once_with(
            [
                UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python,
                "-c",
                "import cv2; import ffmpeg; import tqdm",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )

    def test_backend_available_when_runtime_probe_succeeds(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            real_exists = os.path.exists
            self._materialize_backend_assets(engine_dir, weights_dir)

            with (
                patch("app.upscaler.shutil.which", return_value="ffmpeg"),
                patch("app.upscaler.os.path.exists") as mock_exists,
                patch("app.upscaler.subprocess.run") as mock_run,
            ):
                mock_run.return_value = SimpleNamespace(returncode=0)

                def exists(path: str) -> bool:
                    if path == UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python:
                        return True
                    return real_exists(path)

                mock_exists.side_effect = exists
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertIn("realesrgan-animevideov3", available)
        mock_run.assert_called_once_with(
            [
                UPSCALE_BACKENDS["realesrgan-animevideov3"].runtime_python,
                "-c",
                "import cv2; import ffmpeg; import tqdm",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )

    def test_backend_unavailable_when_required_command_missing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as engine_dir,
            tempfile.TemporaryDirectory() as weights_dir,
        ):
            Path(engine_dir, "seedvr2", "projects").mkdir(parents=True)
            Path(
                engine_dir, "seedvr2", "projects", "inference_seedvr2_3b.py"
            ).write_text("x")
            Path(weights_dir, "seedvr2").mkdir(parents=True)
            for filename in (
                "seedvr2_ema_3b.pth",
                "ema_vae.pth",
                "pos_emb.pt",
                "neg_emb.pt",
            ):
                Path(weights_dir, "seedvr2", filename).write_text("x")

            with patch("app.upscaler.shutil.which", return_value=None):
                available = get_available_upscale_backends(engine_dir, weights_dir)

        self.assertNotIn("seedvr2-3b", available)


class RealESRGANBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = RealESRGANBackend()

    def test_build_command_basic(self) -> None:
        cmd = self.backend.build_command(
            input_path="/input/video.mp4",
            output_dir="/output",
            engine_dir="/engines/upscale",
            weights_dir="/models",
            scale=2,
        )
        self.assertEqual(cmd[0], self.backend.runtime_python)
        cmd_str = " ".join(cmd)
        self.assertIn("/engines/upscale/realesrgan/runner.py", cmd_str)
        self.assertNotIn("adapter.py", cmd_str)
        self.assertIn("--model_path", cmd_str)
        self.assertIn(
            f"/models/{self.backend.weight_family}/{self.backend.weight_filename}",
            cmd_str,
        )
        self.assertNotIn("/models/upscale/", cmd_str)
        self.assertIn("-i", cmd_str)
        self.assertIn("/input/video.mp4", cmd_str)
        self.assertIn("-o", cmd_str)
        self.assertIn("/output", cmd_str)
        self.assertIn("-n", cmd_str)
        self.assertIn("realesr-animevideov3", cmd_str)
        self.assertIn("-s", cmd_str)
        self.assertNotIn("--half", cmd_str)

    def test_validate_params_rejects_exceed_max_scale(self) -> None:
        result = self.backend.validate_params(scale=8)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_validate_params_accepts_valid_scale(self) -> None:
        result = self.backend.validate_params(scale=2)
        self.assertIsNone(result)

    def test_build_command_ignores_target_resolution_fields(self) -> None:
        cmd = self.backend.build_command(
            input_path="/input/video.mp4",
            output_dir="/output",
            engine_dir="/engines/upscale",
            weights_dir="/models",
            scale=2,
            target_width=1280,
            target_height=720,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("/engines/upscale/realesrgan/runner.py", cmd_str)
        self.assertNotIn("1280", cmd_str)
        self.assertNotIn("720", cmd_str)
        self.assertIn("-s", cmd_str)


class RealBasicVSRBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = RealBasicVSRBackend()

    def test_validate_params_rejects_non_4x(self) -> None:
        result = self.backend.validate_params(scale=2)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_validate_params_accepts_4x(self) -> None:
        result = self.backend.validate_params(scale=4)
        self.assertIsNone(result)

    def test_build_command_contains_expected_args(self) -> None:
        cmd = self.backend.build_command(
            input_path="/input/video.mp4",
            output_dir="/output",
            engine_dir="/engines/upscale",
            weights_dir="/models",
            scale=4,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("inference_realbasicvsr.py", cmd_str)
        self.assertIn("/engines/upscale/realbasicvsr", cmd_str)
        self.assertIn("/models/realbasicvsr", cmd_str)
        self.assertIn("--max-seq-len", cmd_str)
        self.assertIn("30", cmd_str)


class SeedVR2BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = SeedVR2Backend()

    def test_validate_params_rejects_non_multiple_32(self) -> None:
        # 448 * 3 + 1 = 1345, 1345 % 32 != 0
        result = self.backend.validate_params(
            scale=3, target_width=1345, target_height=1345
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_validate_params_accepts_multiple_32(self) -> None:
        # 448 * 2 = 896, 896 % 32 == 0
        result = self.backend.validate_params(
            scale=2, target_width=896, target_height=896
        )
        self.assertIsNone(result)

    def test_validate_params_rejects_scale_over_max(self) -> None:
        result = self.backend.validate_params(
            scale=8, target_width=3584, target_height=3584
        )
        self.assertIsNotNone(result)

    def test_build_command_contains_torchrun(self) -> None:
        cmd = self.backend.build_command(
            input_path="/input/video.mp4",
            output_dir="/output",
            engine_dir="/engines/upscale",
            weights_dir="/models",
            scale=2,
            target_width=896,
            target_height=448,
        )
        cmd_str = " ".join(cmd)
        self.assertIn("torchrun", cmd_str)
        self.assertIn("--nproc_per_node=1", cmd_str)
        self.assertIn("--res_h", cmd_str)
        self.assertIn("--res_w", cmd_str)
        self.assertIn("--sp_size", cmd_str)


class UpscaleVideoTests(unittest.TestCase):
    def test_upscale_video_raises_on_unknown_model(self) -> None:
        with self.assertRaises(ValueError):
            upscale_video(
                input_path="/input/video.mp4",
                output_path="/output/video.mp4",
                model="nonexistent",
            )

    @patch("app.process_runner.subprocess.Popen")
    @patch("app.upscaler.os.path.exists", return_value=True)
    def test_upscale_video_calls_popen_and_returns_result(
        self, mock_exists, mock_popen
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = upscale_video(
            input_path="/input/video.mp4",
            output_path="/output/video.mp4",
            model="realesrgan-animevideov3",
            scale=2,
            engine_dir="/engines/upscale",
            weights_dir="/models",
        )

        self.assertEqual(result["output_path"], "/output/video.mp4")
        self.assertEqual(result["model"], "realesrgan-animevideov3")
        self.assertEqual(result["scale"], 2)
        mock_popen.assert_called_once()

    @patch("app.upscaler.os.makedirs")
    @patch("app.upscaler.os.replace")
    @patch("app.upscaler.os.path.isfile", return_value=True)
    @patch("app.upscaler.os.listdir", return_value=["video_out.mp4"])
    @patch("app.upscaler.os.path.exists")
    @patch("app.upscaler.run_cancellable_process")
    def test_upscale_video_relocates_realesrgan_output_to_expected_path(
        self,
        mock_run,
        mock_exists,
        mock_listdir,
        mock_isfile,
        mock_replace,
        mock_makedirs,
    ) -> None:
        mock_result = SimpleNamespace(
            process=SimpleNamespace(returncode=0),
            stdout=b"ok",
            stderr=b"",
        )
        mock_run.return_value = mock_result

        def exists(path: str) -> bool:
            if path == "/output/video.mp4":
                return False
            if path == "/output/video_out.mp4":
                return True
            return False

        mock_exists.side_effect = exists

        result = upscale_video(
            input_path="/input/video.mp4",
            output_path="/output/video.mp4",
            model="realesrgan-animevideov3",
            scale=2,
            engine_dir="/engines/upscale",
            weights_dir="/models",
        )

        self.assertEqual(result["output_path"], "/output/video.mp4")
        expected_candidate = os.path.join("/output", "video_out.mp4")
        mock_replace.assert_called_once_with(
            expected_candidate,
            "/output/video.mp4",
        )

    @patch("app.process_runner.subprocess.Popen")
    def test_upscale_video_raises_on_nonzero_returncode(self, mock_popen) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"error details here")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        with self.assertRaises(RuntimeError):
            upscale_video(
                input_path="/input/video.mp4",
                output_path="/output/video.mp4",
                model="realesrgan-animevideov3",
                scale=2,
            )

    @patch("app.process_runner.subprocess.Popen")
    def test_upscale_video_raises_on_timeout(self, mock_popen) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.kill = MagicMock()
        mock_popen.return_value = mock_proc

        with patch("app.process_runner.time.monotonic", side_effect=[0.0, 1801.0]):
            with self.assertRaises(TimeoutError):
                upscale_video(
                    input_path="/input/video.mp4",
                    output_path="/output/video.mp4",
                    model="realesrgan-animevideov3",
                    scale=2,
                )
        mock_proc.kill.assert_called()

    @patch("app.process_runner.subprocess.Popen")
    @patch("app.upscaler.os.path.exists", return_value=False)
    def test_upscale_video_raises_on_missing_output(
        self, mock_exists, mock_popen
    ) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        with self.assertRaises(FileNotFoundError):
            upscale_video(
                input_path="/input/video.mp4",
                output_path="/output/video.mp4",
                model="realesrgan-animevideov3",
                scale=2,
            )

    @patch("app.process_runner.subprocess.Popen")
    def test_upscale_video_cancels_when_worker_requests_abort(self, mock_popen) -> None:
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="python", timeout=1800),
            (b"", b""),
        ]
        mock_proc.kill = MagicMock()
        mock_popen.return_value = mock_proc

        cancel_checks = iter([False, True])

        with self.assertRaises(UpscaleCancelledError):
            upscale_video(
                input_path="/input/video.mp4",
                output_path="/output/video.mp4",
                model="realesrgan-animevideov3",
                scale=2,
                should_cancel=lambda: next(cancel_checks),
            )

        mock_proc.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
