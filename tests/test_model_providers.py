import contextlib
import hashlib
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from app.backends.providers import HuggingFaceProvider, HttpProvider, SubmoduleProvider
from app.backends.model_spec import FileCheck, ModelSpec
from app.settings import load_settings
from app.upscale_contract import (
    REALESRGAN_ENGINE_FILES,
    REALESRGAN_WEIGHT_FAMILY,
    REALESRGAN_WEIGHT_FILENAME,
)


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

    @patch("app.backends.providers.os.path.exists", return_value=True)
    def test_ensure_passes_when_file_exists(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        self.provider.ensure(spec)  # Should not raise

    @patch("app.backends.providers.os.path.exists", return_value=False)
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

    @patch("app.backends.providers.os.path.exists", return_value=True)
    def test_verify_passes_when_file_exists(self, mock_exists) -> None:
        spec = ModelSpec(
            name="test-engine",
            source_type="submodule",
            source_ref="",
            target_dir="/engines/test",
            files=[FileCheck(path="run.py")],
        )
        self.provider.verify(spec)  # Should not raise

    @patch("app.backends.providers.os.path.exists", return_value=False)
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

    @patch("app.backends.providers.os.path.isfile", return_value=True)
    def test_ensure_skips_download_when_files_exist(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with patch("app.backends.providers.snapshot_download") as mock_dl:
            self.provider.ensure(spec)
            mock_dl.assert_not_called()

    @patch("app.backends.providers.os.path.isfile", return_value=False)
    def test_ensure_downloads_when_files_missing(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        with patch("app.backends.providers.snapshot_download") as mock_dl:
            mock_isfile.side_effect = [False, True]
            self.provider.ensure(spec)
            mock_dl.assert_called_once_with(
                repo_id="org/model",
                local_dir="/models/test",
            )

    @patch("app.backends.providers.os.path.isfile", return_value=True)
    def test_verify_passes_when_files_exist(self, mock_isfile) -> None:
        spec = ModelSpec(
            name="test-weights",
            source_type="huggingface",
            source_ref="org/model",
            target_dir="/models/test",
            files=[FileCheck(path="weights.bin")],
        )
        self.provider.verify(spec)

    @patch("app.backends.providers.os.path.isfile", return_value=False)
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
            patch("app.backends.providers.os.path.isfile", return_value=False),
            patch("app.backends.providers.snapshot_download", None),
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
            patch("app.backends.providers.os.path.isfile", return_value=True),
            patch("app.backends.providers._check_sha256", return_value=False),
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
            patch("app.backends.providers.os.path.isfile", return_value=False),
            patch("app.backends.providers.snapshot_download") as mock_dl,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.ensure(spec)
            mock_dl.assert_called_once()
            self.assertIn(
                "Download completed but files still missing", str(ctx.exception)
            )


import tempfile
from pathlib import Path


class HttpProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = HttpProvider()

    def _make_spec(self, target_dir: str, sha256: str | None = None) -> ModelSpec:
        return ModelSpec(
            name="test-http",
            source_type="http",
            source_ref="https://example.com/model.bin",
            target_dir=target_dir,
            files=[FileCheck(path="model.bin", sha256=sha256)],
        )

    def test_ensure_skips_when_file_present_and_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = b"hello"
            full = Path(td, "model.bin")
            full.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            spec = self._make_spec(td, sha256=digest)

            with patch("app.backends.providers.urllib.request.urlopen") as mock_open:
                self.provider.ensure(spec)
                mock_open.assert_not_called()

    def test_ensure_downloads_atomically_and_verifies_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = b"binary-content"
            digest = hashlib.sha256(payload).hexdigest()
            spec = self._make_spec(td, sha256=digest)

            mock_response = MagicMock()
            mock_response.read.side_effect = [payload, b""]
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = lambda s, a, b, c: None

            with patch(
                "app.backends.providers.urllib.request.urlopen",
                return_value=mock_response,
            ):
                self.provider.ensure(spec)

            final = Path(td, "model.bin")
            self.assertTrue(final.is_file())
            self.assertEqual(final.read_bytes(), payload)
            self.assertFalse(Path(td, "model.bin.part").exists())

    def test_ensure_raises_and_cleans_temp_on_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec = self._make_spec(td, sha256="00" * 32)

            mock_response = MagicMock()
            mock_response.read.side_effect = [b"wrong-bytes", b""]
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = lambda s, a, b, c: None

            with patch(
                "app.backends.providers.urllib.request.urlopen",
                return_value=mock_response,
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    self.provider.ensure(spec)
            self.assertIn("Hash mismatch", str(ctx.exception))
            self.assertFalse(Path(td, "model.bin").exists())
            self.assertFalse(Path(td, "model.bin.part").exists())

    def test_verify_raises_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec = self._make_spec(td)
            with self.assertRaises(FileNotFoundError):
                self.provider.verify(spec)

    def test_verify_raises_on_sha256_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "model.bin").write_bytes(b"bad")
            spec = self._make_spec(td, sha256="00" * 32)
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.verify(spec)
            self.assertIn("Hash mismatch", str(ctx.exception))

    def test_ensure_rejects_specs_with_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec = ModelSpec(
                name="bad-http",
                source_type="http",
                source_ref="https://example.com/a.bin",
                target_dir=td,
                files=[FileCheck(path="a.bin"), FileCheck(path="b.bin")],
            )
            with self.assertRaises(RuntimeError) as ctx:
                self.provider.ensure(spec)
            self.assertIn("exactly one file", str(ctx.exception))


from app.backends.model_manager import ModelManager


class ModelManagerTests(unittest.TestCase):
    @patch("app.backends.providers.os.path.exists", return_value=True)
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

    @patch("app.backends.providers.os.path.exists", return_value=False)
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

    @patch("app.backends.providers.os.path.exists", return_value=True)
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

    def test_manager_registers_http_source_type(self) -> None:
        manager = ModelManager()
        self.assertIn("http", manager._providers)
        self.assertIsInstance(manager._providers["http"], HttpProvider)


from app.backends.model_specs import load_model_specs


class CLITests(unittest.TestCase):
    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_install_calls_manager_ensure(
        self, mock_specs, mock_manager_cls
    ) -> None:
        from app.backends.cli import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["install"])
        mock_specs.assert_called_once()
        mock_manager_cls.return_value.ensure.assert_called_once_with([])
        self.assertIn("ready", buf.getvalue().lower())

    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_verify_exits_zero_when_all_present(
        self, mock_specs, mock_manager_cls
    ) -> None:
        from app.backends.cli import main

        mock_manager_cls.return_value.verify.return_value = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["verify"])

    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_verify_exits_nonzero_when_missing(
        self, mock_specs, mock_manager_cls
    ) -> None:
        from app.backends.cli import main

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
            "UPSCALE_WEIGHTS_DIR": "/models",
        }
        with patch.dict(os.environ, env, clear=True):
            specs = load_model_specs(load_settings())
        names = [s.name for s in specs]
        self.assertIn("wan-t2v-1.3b", names)
        self.assertIn("panowan-lora", names)
        self.assertIn("panowan-engine", names)
        self.assertIn("upscale-realesrgan-engine", names)
        self.assertIn("upscale-realesrgan-weights", names)
        self.assertEqual(len(specs), 5)

    def test_upscale_engine_spec_is_submodule_type(self) -> None:
        env = {
            "WAN_MODEL_PATH": "/models/Wan-AI/Wan2.1-T2V-1.3B",
            "LORA_CHECKPOINT_PATH": "/models/PanoWan/latest-lora.ckpt",
            "PANOWAN_ENGINE_DIR": "/engines/panowan",
            "UPSCALE_ENGINE_DIR": "/engines/upscale",
            "UPSCALE_WEIGHTS_DIR": "/models",
        }
        with patch.dict(os.environ, env, clear=True):
            specs = load_model_specs(load_settings())
        re_engine = next(s for s in specs if s.name == "upscale-realesrgan-engine")
        self.assertEqual(re_engine.source_type, "submodule")
        self.assertEqual(re_engine.target_dir, "/engines/upscale")
        # The engine spec must derive its file list from the shared contract
        # module so the spec, the upscaler availability check, and the actual
        # vendored layout cannot drift apart.
        self.assertEqual(
            [f.path for f in re_engine.files],
            list(REALESRGAN_ENGINE_FILES),
        )

    def test_upscale_realesrgan_weights_spec_uses_official_http_artifact(self) -> None:
        env = {
            "WAN_MODEL_PATH": "/models/Wan-AI/Wan2.1-T2V-1.3B",
            "LORA_CHECKPOINT_PATH": "/models/PanoWan/latest-lora.ckpt",
            "PANOWAN_ENGINE_DIR": "/engines/panowan",
            "UPSCALE_ENGINE_DIR": "/engines/upscale",
            "UPSCALE_WEIGHTS_DIR": "/models",
        }
        with patch.dict(os.environ, env, clear=True):
            specs = load_model_specs(load_settings())
        weights = next(s for s in specs if s.name == "upscale-realesrgan-weights")
        self.assertEqual(weights.source_type, "http")
        self.assertEqual(
            weights.source_ref,
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
        )
        self.assertEqual(weights.target_dir, f"/models/{REALESRGAN_WEIGHT_FAMILY}")
        self.assertEqual([f.path for f in weights.files], [REALESRGAN_WEIGHT_FILENAME])
        self.assertTrue(weights.files[0].sha256)
