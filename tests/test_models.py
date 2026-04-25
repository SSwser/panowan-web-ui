import contextlib
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from app.models.providers import HuggingFaceProvider, SubmoduleProvider
from app.models.registry import FileCheck, ModelSpec
from app.settings import load_settings


class ModelSpecTests(unittest.TestCase):
    def test_modelspec_is_frozen(self) -> None:
        spec = ModelSpec(
            name="test",
            source_type="huggingface",
            source_ref="org/repo",
            target_dir="/models/test",
            files=[FileCheck(path="model.bin")],
        )
        with self.assertRaises(AttributeError):
            spec.name = "changed"

    def test_filecheck_is_frozen(self) -> None:
        fc = FileCheck(path="model.bin", sha256="abc123")
        with self.assertRaises(AttributeError):
            fc.path = "other.bin"

    def test_filecheck_sha256_defaults_to_none(self) -> None:
        fc = FileCheck(path="model.bin")
        self.assertIsNone(fc.sha256)


class SubmoduleProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = SubmoduleProvider()

    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_ensure_passes_when_file_exists(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        self.provider.ensure(spec)  # Should not raise

    @patch("app.models.providers.os.path.exists", return_value=False)
    def test_ensure_raises_when_file_missing(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        with self.assertRaises(FileNotFoundError) as ctx:
            self.provider.ensure(spec)
        message = str(ctx.exception).lower()
        self.assertIn("submodule", message)
        self.assertIn("third_party", message)

    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_verify_passes_when_file_exists(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        self.provider.verify(spec)  # Should not raise

    @patch("app.models.providers.os.path.exists", return_value=False)
    def test_verify_raises_when_file_missing(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        with self.assertRaises(FileNotFoundError):
            self.provider.verify(spec)


class HuggingFaceProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = HuggingFaceProvider()

    @patch("app.models.providers.os.path.isfile", return_value=True)
    def test_ensure_skips_download_when_files_exist(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with patch("app.models.providers.snapshot_download") as mock_dl:
            self.provider.ensure(spec)
            mock_dl.assert_not_called()

    @patch("app.models.providers.os.path.isfile", return_value=False)
    def test_ensure_downloads_when_files_missing(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with patch("app.models.providers.snapshot_download") as mock_dl:
            mock_isfile.side_effect = [False, True]
            self.provider.ensure(spec)
            mock_dl.assert_called_once_with(
                repo_id="org/model",
                local_dir="/models/test",
            )

    @patch("app.models.providers.os.path.isfile", return_value=True)
    def test_verify_passes_when_files_exist(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        self.provider.verify(spec)

    @patch("app.models.providers.os.path.isfile", return_value=False)
    def test_verify_raises_when_files_missing(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with self.assertRaises(FileNotFoundError):
            self.provider.verify(spec)

    def test_ensure_raises_runtime_error_when_huggingface_hub_unavailable(self) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with (
            patch("app.models.providers.os.path.isfile", return_value=False),
            patch("app.models.providers.snapshot_download", None),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.ensure(spec)
            self.assertIn("huggingface_hub", str(ctx.exception))
            self.assertIn("pip install", str(ctx.exception))

    def test_verify_raises_runtime_error_on_sha256_mismatch(self) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin", sha256="deadbeef")],
        )
        with (
            patch("app.models.providers.os.path.isfile", return_value=True),
            patch("app.models.providers._check_sha256", return_value=False),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.verify(spec)
            self.assertIn("Hash mismatch", str(ctx.exception))

    def test_ensure_raises_when_files_still_missing_after_download(self) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with (
            patch("app.models.providers.os.path.isfile", return_value=False),
            patch("app.models.providers.snapshot_download") as mock_dl,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.ensure(spec)
            mock_dl.assert_called_once()
            self.assertIn(
                "Download completed but files still missing", str(ctx.exception)
            )


from app.models.manager import ModelManager


class ModelManagerTests(unittest.TestCase):
    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_ensure_calls_provider_for_each_spec(self, mock_exists) -> None:
        spec1 = ModelSpec(
            name="engine-a",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/a",
            files=[FileCheck(path="run.py")],
        )
        spec2 = ModelSpec(
            name="engine-b",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/b",
            files=[FileCheck(path="run.py")],
        )
        manager = ModelManager()
        manager.ensure([spec1, spec2])  # Should not raise

    @patch("app.models.providers.os.path.exists", return_value=False)
    def test_verify_returns_missing_spec_names(self, mock_exists) -> None:
        spec1 = ModelSpec(
            name="missing-a",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/a",
            files=[FileCheck(path="run.py")],
        )
        spec2 = ModelSpec(
            name="missing-b",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/b",
            files=[FileCheck(path="run.py")],
        )
        manager = ModelManager()
        missing = manager.verify([spec1, spec2])
        self.assertEqual(missing, ["missing-a", "missing-b"])

    @patch("app.models.providers.os.path.exists", return_value=True)
    def test_verify_returns_empty_when_all_present(self, mock_exists) -> None:
        spec = ModelSpec(
            name="present-a",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/a",
            files=[FileCheck(path="run.py")],
        )
        manager = ModelManager()
        missing = manager.verify([spec])
        self.assertEqual(missing, [])


from app.models.specs import load_specs


class CLITests(unittest.TestCase):
    @patch("app.models.__main__.load_settings")
    @patch("app.models.__main__.ModelManager")
    @patch("app.models.__main__.load_specs", return_value=[])
    def test_cli_ensure_calls_manager_ensure(
        self, mock_specs, mock_manager_cls, mock_load_settings
    ) -> None:
        from app.models.__main__ import main

        mock_load_settings.return_value = MagicMock()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["ensure"])
        mock_specs.assert_called_once_with(mock_load_settings.return_value)
        mock_manager_cls.return_value.ensure.assert_called_once_with([])
        self.assertIn("ready", buf.getvalue().lower())

    @patch("app.models.__main__.load_settings")
    @patch("app.models.__main__.ModelManager")
    @patch("app.models.__main__.load_specs", return_value=[])
    def test_cli_verify_exits_zero_when_all_present(
        self, mock_specs, mock_manager_cls, mock_load_settings
    ) -> None:
        from app.models.__main__ import main

        mock_load_settings.return_value = MagicMock()
        mock_manager_cls.return_value.verify.return_value = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["verify"])

    @patch("app.models.__main__.load_settings")
    @patch("app.models.__main__.ModelManager")
    @patch("app.models.__main__.load_specs", return_value=[])
    def test_cli_verify_exits_nonzero_when_missing(
        self, mock_specs, mock_manager_cls, mock_load_settings
    ) -> None:
        from app.models.__main__ import main

        mock_load_settings.return_value = MagicMock()
        mock_manager_cls.return_value.verify.return_value = ["missing-model"]
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(buf):
            main(["verify"])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("missing-model", buf.getvalue())


class LoadSpecsTests(unittest.TestCase):
    def test_load_specs_returns_expected_spec_names(self) -> None:
        env = {
            "WAN_MODEL_PATH": "/models/Wan-AI/Wan2.1-T2V-1.3B",
            "LORA_CHECKPOINT_PATH": "/models/PanoWan/latest-lora.ckpt",
            "PANOWAN_ENGINE_DIR": "/engines/panowan",
            "UPSCALE_ENGINE_DIR": "/engines/upscale",
            "UPSCALE_WEIGHTS_DIR": "/models/upscale",
        }
        with patch.dict(os.environ, env, clear=True):
            specs = load_specs(load_settings())
        names = [s.name for s in specs]
        self.assertIn("wan-t2v-1.3b", names)
        self.assertIn("panowan-lora", names)
        self.assertIn("panowan-engine", names)
        self.assertIn("upscale-engine", names)
        self.assertIn("realesrgan-weights", names)
        self.assertEqual(len(specs), 5)

    def test_upscale_engine_spec_is_submodule_type(self) -> None:
        env = {
            "WAN_MODEL_PATH": "/models/Wan-AI/Wan2.1-T2V-1.3B",
            "LORA_CHECKPOINT_PATH": "/models/PanoWan/latest-lora.ckpt",
            "PANOWAN_ENGINE_DIR": "/engines/panowan",
            "UPSCALE_ENGINE_DIR": "/engines/upscale",
            "UPSCALE_WEIGHTS_DIR": "/models/upscale",
        }
        with patch.dict(os.environ, env, clear=True):
            specs = load_specs(load_settings())
        re_engine = next(s for s in specs if s.name == "upscale-engine")
        self.assertEqual(re_engine.source_type, "submodule")
        self.assertEqual(re_engine.target_dir, "/engines/upscale")
        self.assertEqual(
            re_engine.files,
            [FileCheck(path="realesrgan/inference_realesrgan_video.py")],
        )
