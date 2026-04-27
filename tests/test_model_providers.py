import contextlib
import hashlib
import io
import os
import shutil
import sys
import unittest
from unittest.mock import MagicMock, patch

from app.backends.providers import HuggingFaceProvider, HttpProvider, SubmoduleProvider
from pathlib import Path

from app.backends.registry import discover
from app.backends.spec import (
    BackendSection,
    BackendSpec,
    FilterSpec,
    OutputSpec,
    RuntimeInputsSpec,
    RuntimeSpec,
    SourceSpec,
    WeightsSpec,
)
from app.backends.verify import ensure_backend, expected_backend_files, verify_backend
from app.backends.model_spec import FileCheck, ModelSpec
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
    @patch("app.backends.cli.discover", return_value=[])
    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_install_calls_manager_ensure(
        self, mock_specs, mock_manager_cls, mock_discover
    ) -> None:
        from app.backends.cli import main

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["install"])
        mock_specs.assert_called_once()
        mock_manager_cls.return_value.ensure.assert_called_once_with([])
        self.assertIn("ready", buf.getvalue().lower())

    @patch("app.backends.cli.discover", return_value=[])
    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_verify_exits_zero_when_all_present(
        self, mock_specs, mock_manager_cls, mock_discover
    ) -> None:
        from app.backends.cli import main

        mock_manager_cls.return_value.verify.return_value = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["verify"])
        self.assertIn("verified", buf.getvalue().lower())

    @patch("app.backends.cli.discover", return_value=[])
    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_verify_exits_nonzero_when_missing(
        self, mock_specs, mock_manager_cls, mock_discover
    ) -> None:
        from app.backends.cli import main

        mock_manager_cls.return_value.verify.return_value = ["missing-model"]
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(buf):
            main(["verify"])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("missing-model", buf.getvalue())

    @patch("app.backends.cli.discover", return_value=[])
    @patch("app.backends.cli.ModelManager")
    @patch("app.backends.cli.load_model_specs", return_value=[])
    def test_cli_list_prints_model_specs_when_no_backends(
        self, mock_specs, mock_manager_cls, mock_discover
    ) -> None:
        from app.backends.cli import main

        mock_specs.return_value = [
            ModelSpec(
                name="wan-t2v-1.3b",
                source_type="huggingface",
                source_ref="org/repo",
                target_dir="/models/test",
                files=[FileCheck(path="weights.bin")],
            )
        ]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["list"])
        self.assertIn("wan-t2v-1.3b", buf.getvalue())
        mock_manager_cls.assert_called_once()
        mock_discover.assert_called_once()


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
        self.assertIn("upscale-realesrgan-weights", names)
        self.assertNotIn("upscale-realesrgan-engine", names)
        self.assertEqual(len(specs), 4)

    def test_realesrgan_backend_spec_drives_engine_file_contract(self) -> None:
        realesrgan = next(
            spec
            for spec in discover(Path("third_party/Upscale"))
            if spec.backend.name == "realesrgan"
        )
        engine_files = [
            "realesrgan/runner.py",
            *[f"realesrgan/{path}" for path in expected_backend_files(realesrgan)],
        ]
        self.assertIn("realesrgan/runner.py", engine_files)
        self.assertIn("realesrgan/__main__.py", engine_files)
        self.assertIn("realesrgan/inference_realesrgan_video.py", engine_files)
        self.assertTrue(all(path.startswith("realesrgan/") for path in engine_files))
        self.assertIn("realesrgan/realesrgan/srvgg_arch.py", engine_files)
        self.assertIn("realesrgan/realesrgan/utils.py", engine_files)
        self.assertIn("realesrgan/realesrgan/__init__.py", engine_files)
        self.assertEqual(engine_files[0], "realesrgan/runner.py")
        self.assertEqual(len(engine_files), 6)
        self.assertEqual(
            realesrgan.weights.required_files, ["Real-ESRGAN/realesr-animevideov3.pth"]
        )
        self.assertEqual(realesrgan.runtime.required_commands, ["ffmpeg"])
        self.assertEqual(
            realesrgan.runtime.required_python_modules,
            ["cv2", "ffmpeg", "tqdm"],
        )
        self.assertEqual(
            realesrgan.runtime.python, "/opt/venvs/upscale-realesrgan/bin/python"
        )
        self.assertEqual(realesrgan.weights.family, "Real-ESRGAN")
        self.assertEqual(realesrgan.weights.filename, "realesr-animevideov3.pth")

    def test_expected_backend_files_prefers_explicit_contract_when_present(
        self,
    ) -> None:
        spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(
                include=[
                    "inference/Real-ESRGAN/inference_realesrgan_video.py",
                    "realesrgan/Real-ESRGAN/realesrgan/**",
                ],
                exclude=[],
            ),
            output=OutputSpec(
                target="vendor",
                strip_prefixes=[
                    "inference/Real-ESRGAN/",
                    "realesrgan/Real-ESRGAN/",
                ],
                expected_files=[
                    "__main__.py",
                    "inference_realesrgan_video.py",
                    "realesrgan/__init__.py",
                ],
            ),
            runtime=RuntimeSpec(
                python="/opt/venvs/upscale-realesrgan/bin/python",
                required_commands=["ffmpeg"],
                required_python_modules=["cv2", "ffmpeg", "tqdm"],
            ),
            weights=WeightsSpec(
                family="Real-ESRGAN",
                filename="realesr-animevideov3.pth",
                required_files=["Real-ESRGAN/realesr-animevideov3.pth"],
            ),
        )
        self.assertEqual(
            expected_backend_files(spec),
            [
                "__main__.py",
                "inference_realesrgan_video.py",
                "realesrgan/__init__.py",
            ],
        )

    def test_expected_backend_files_rewrite_filtered_paths_for_vendor_layout(
        self,
    ) -> None:
        spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(
                include=[
                    "inference/Real-ESRGAN/inference_realesrgan_video.py",
                    "realesrgan/Real-ESRGAN/realesrgan/**",
                ],
                exclude=[],
            ),
            output=OutputSpec(
                target="vendor",
                strip_prefixes=[
                    "inference/Real-ESRGAN/",
                    "realesrgan/Real-ESRGAN/",
                ],
            ),
        )
        self.assertEqual(
            expected_backend_files(spec),
            ["inference_realesrgan_video.py", "realesrgan"],
        )

    def test_ensure_backend_rebuilds_with_runtime_input_files(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as src:
            root = Path(td)
            runtime_input_root = root / "sources" / "realesrgan"
            runtime_input_root.mkdir(parents=True)
            (root / "sources" / "__main__.py").write_text("entry", encoding="utf-8")
            (runtime_input_root / "__init__.py").write_text("pkg", encoding="utf-8")

            src_root = Path(src)
            (src_root / "inference" / "Real-ESRGAN").mkdir(parents=True)
            (
                src_root / "inference" / "Real-ESRGAN" / "inference_realesrgan_video.py"
            ).write_text("runner", encoding="utf-8")

            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(
                    include=["inference/Real-ESRGAN/inference_realesrgan_video.py"],
                    exclude=[],
                ),
                output=OutputSpec(
                    target="vendor",
                    strip_prefixes=["inference/Real-ESRGAN/"],
                    expected_files=[
                        "__main__.py",
                        "inference_realesrgan_video.py",
                        "realesrgan/__init__.py",
                    ],
                ),
                runtime_inputs=RuntimeInputsSpec(
                    root="sources",
                    files=["__main__.py", "realesrgan/__init__.py"],
                ),
            )

            class TempDirStub:
                def __init__(self, name: str) -> None:
                    self.name = name

                def cleanup(self) -> None:
                    return None

            with patch(
                "app.backends.verify.acquire_backend_source",
                return_value=TempDirStub(src),
            ):
                status = ensure_backend(spec)

            self.assertEqual(status, "rebuilt")
            self.assertEqual(
                (root / "vendor" / ".revision").read_text(encoding="utf-8").strip(),
                "v1",
            )
            self.assertEqual(
                (root / "vendor" / "inference_realesrgan_video.py").read_text(
                    encoding="utf-8"
                ),
                "runner",
            )
            self.assertEqual(
                (root / "vendor" / "__main__.py").read_text(encoding="utf-8"),
                "entry",
            )
            self.assertEqual(
                (root / "vendor" / "realesrgan" / "__init__.py").read_text(
                    encoding="utf-8"
                ),
                "pkg",
            )
            self.assertFalse((root / "vendor" / "inference").exists())

    def test_expected_backend_files_include_runtime_inputs_when_output_contract_is_implicit(
        self,
    ) -> None:
        spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git",
                url="https://example.invalid/realesrgan.git",
                revision="v1",
            ),
            filter=FilterSpec(
                include=["inference/Real-ESRGAN/inference_realesrgan_video.py"],
                exclude=[],
            ),
            output=OutputSpec(
                target="vendor",
                strip_prefixes=["inference/Real-ESRGAN/"],
            ),
            runtime_inputs=RuntimeInputsSpec(
                root="sources",
                files=["__main__.py", "realesrgan/__init__.py"],
            ),
        )
        self.assertEqual(
            expected_backend_files(spec),
            [
                "inference_realesrgan_video.py",
                "__main__.py",
                "realesrgan/__init__.py",
            ],
        )

    def test_expected_backend_files_use_authoritative_runtime_inputs(self) -> None:
        spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git",
                url="https://example.invalid/realesrgan.git",
                revision="v1",
            ),
            filter=FilterSpec(
                include=["inference/Real-ESRGAN/inference_realesrgan_video.py"],
                exclude=[],
            ),
            output=OutputSpec(target="vendor"),
            runtime_inputs=RuntimeInputsSpec(
                root="sources",
                authoritative=True,
                files=["__main__.py", "realesrgan/__init__.py"],
            ),
        )
        self.assertEqual(
            expected_backend_files(spec),
            ["__main__.py", "realesrgan/__init__.py"],
        )

    def test_ensure_backend_rebuilds_from_authoritative_runtime_inputs_without_upstream(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources" / "realesrgan").mkdir(parents=True)
            (root / "sources" / "__main__.py").write_text("entry", encoding="utf-8")
            (root / "sources" / "realesrgan" / "__init__.py").write_text(
                "pkg", encoding="utf-8"
            )

            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(include=[], exclude=[]),
                output=OutputSpec(target="vendor"),
                runtime_inputs=RuntimeInputsSpec(
                    root="sources",
                    authoritative=True,
                    files=["__main__.py", "realesrgan/__init__.py"],
                ),
            )

            with patch("app.backends.verify.acquire_backend_source") as mock_acquire:
                status = ensure_backend(spec)

            self.assertEqual(status, "rebuilt")
            mock_acquire.assert_not_called()
            self.assertEqual(
                (root / "vendor" / "__main__.py").read_text(encoding="utf-8"), "entry"
            )
            self.assertEqual(
                (root / "vendor" / "realesrgan" / "__init__.py").read_text(
                    encoding="utf-8"
                ),
                "pkg",
            )
            self.assertEqual(
                (root / "vendor" / ".revision").read_text(encoding="utf-8").strip(),
                "v1",
            )

    def test_ensure_backend_rebuilds_when_authoritative_runtime_inputs_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / ".revision").write_text("v1\n", encoding="utf-8")
            (vendor / "__main__.py").write_text("entry", encoding="utf-8")

            (root / "sources" / "realesrgan").mkdir(parents=True)
            (root / "sources" / "__main__.py").write_text("entry", encoding="utf-8")
            (root / "sources" / "realesrgan" / "__init__.py").write_text(
                "pkg", encoding="utf-8"
            )

            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(include=[], exclude=[]),
                output=OutputSpec(target="vendor"),
                runtime_inputs=RuntimeInputsSpec(
                    root="sources",
                    authoritative=True,
                    files=["__main__.py", "realesrgan/__init__.py"],
                ),
            )

            with patch("app.backends.verify.acquire_backend_source") as mock_acquire:
                status = ensure_backend(spec)

            self.assertEqual(status, "rebuilt")
            mock_acquire.assert_not_called()
            self.assertEqual(
                (vendor / "realesrgan" / "__init__.py").read_text(encoding="utf-8"),
                "pkg",
            )
            self.assertFalse((vendor / "stale.txt").exists())

    def test_ensure_backend_rebuilds_authoritative_runtime_after_vendor_is_deleted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sources" / "realesrgan" / "archs").mkdir(parents=True)
            (root / "sources" / "__main__.py").write_text("entry", encoding="utf-8")
            (root / "sources" / "inference_realesrgan_video.py").write_text(
                "runner", encoding="utf-8"
            )
            (root / "sources" / "realesrgan" / "__init__.py").write_text(
                "pkg", encoding="utf-8"
            )
            (root / "sources" / "realesrgan" / "archs" / "__init__.py").write_text(
                "arch", encoding="utf-8"
            )

            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(include=[], exclude=[]),
                output=OutputSpec(target="vendor"),
                runtime_inputs=RuntimeInputsSpec(
                    root="sources",
                    authoritative=True,
                    files=[
                        "__main__.py",
                        "inference_realesrgan_video.py",
                        "realesrgan/__init__.py",
                    ],
                ),
            )

            with patch("app.backends.verify.acquire_backend_source") as mock_acquire:
                self.assertEqual(ensure_backend(spec), "rebuilt")
                shutil.rmtree(root / "vendor")
                self.assertEqual(ensure_backend(spec), "rebuilt")

            mock_acquire.assert_not_called()
            self.assertEqual(
                (root / "vendor" / "__main__.py").read_text(encoding="utf-8"), "entry"
            )
            self.assertEqual(
                (root / "vendor" / "inference_realesrgan_video.py").read_text(
                    encoding="utf-8"
                ),
                "runner",
            )
            self.assertEqual(
                (root / "vendor" / "realesrgan" / "__init__.py").read_text(
                    encoding="utf-8"
                ),
                "pkg",
            )
            self.assertEqual(
                (root / "vendor" / ".revision").read_text(encoding="utf-8").strip(),
                "v1",
            )
            self.assertFalse((root / "vendor" / ".git").exists())

    def test_verify_backend_reports_missing_without_revision_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = verify_backend("v1", Path(td), ["__main__.py"])
        self.assertEqual(result.status, "missing")
        self.assertEqual(result.revision, None)
        self.assertEqual(result.missing_files, ["__main__.py"])

    def test_ensure_backend_rebuilds_when_runtime_inputs_are_missing_from_implicit_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as src:
            root = Path(td)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / ".revision").write_text("v1\n", encoding="utf-8")
            (vendor / "inference_realesrgan_video.py").write_text(
                "runner", encoding="utf-8"
            )

            (root / "sources" / "realesrgan").mkdir(parents=True)
            (root / "sources" / "__main__.py").write_text("entry", encoding="utf-8")
            (root / "sources" / "realesrgan" / "__init__.py").write_text(
                "pkg", encoding="utf-8"
            )

            src_root = Path(src)
            (src_root / "inference" / "Real-ESRGAN").mkdir(parents=True)
            (
                src_root / "inference" / "Real-ESRGAN" / "inference_realesrgan_video.py"
            ).write_text("runner", encoding="utf-8")

            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(
                    include=["inference/Real-ESRGAN/inference_realesrgan_video.py"],
                    exclude=[],
                ),
                output=OutputSpec(
                    target="vendor",
                    strip_prefixes=["inference/Real-ESRGAN/"],
                ),
                runtime_inputs=RuntimeInputsSpec(
                    root="sources",
                    files=["__main__.py", "realesrgan/__init__.py"],
                ),
            )

            class TempDirStub:
                def __init__(self, name: str) -> None:
                    self.name = name

                def cleanup(self) -> None:
                    return None

            with patch(
                "app.backends.verify.acquire_backend_source",
                return_value=TempDirStub(src),
            ):
                status = ensure_backend(spec)

            self.assertEqual(status, "rebuilt")
            self.assertEqual(
                (vendor / "__main__.py").read_text(encoding="utf-8"), "entry"
            )
            self.assertEqual(
                (vendor / "realesrgan" / "__init__.py").read_text(encoding="utf-8"),
                "pkg",
            )

    def test_ensure_backend_skips_when_revision_and_files_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / ".revision").write_text("v1\n", encoding="utf-8")
            (vendor / "inference_realesrgan_video.py").write_text("x", encoding="utf-8")
            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(
                    include=["inference/inference_realesrgan_video.py"], exclude=[]
                ),
                output=OutputSpec(target="vendor", strip_prefixes=["inference/"]),
            )
            with patch("app.backends.verify.acquire_backend_source") as mock_acquire:
                status = ensure_backend(spec)
            self.assertEqual(status, "ok")
            mock_acquire.assert_not_called()

    def test_ensure_backend_rebuilds_when_vendor_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as src:
            root = Path(td)
            src_root = Path(src)
            (src_root / "inference" / "Real-ESRGAN").mkdir(parents=True)
            (
                src_root / "inference" / "Real-ESRGAN" / "inference_realesrgan_video.py"
            ).write_text("runner", encoding="utf-8")
            (src_root / "realesrgan" / "Real-ESRGAN" / "realesrgan").mkdir(parents=True)
            (
                src_root / "realesrgan" / "Real-ESRGAN" / "realesrgan" / "__init__.py"
            ).write_text("pkg", encoding="utf-8")
            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(
                    include=[
                        "inference/Real-ESRGAN/inference_realesrgan_video.py",
                        "realesrgan/Real-ESRGAN/realesrgan/**",
                    ],
                    exclude=[],
                ),
                output=OutputSpec(
                    target="vendor",
                    strip_prefixes=[
                        "inference/Real-ESRGAN/",
                        "realesrgan/Real-ESRGAN/",
                    ],
                ),
            )

            class TempDirStub:
                def __init__(self, name: str) -> None:
                    self.name = name

                def cleanup(self) -> None:
                    return None

            with patch(
                "app.backends.verify.acquire_backend_source",
                return_value=TempDirStub(src),
            ):
                status = ensure_backend(spec)

            self.assertEqual(status, "rebuilt")
            self.assertEqual(
                (root / "vendor" / ".revision").read_text(encoding="utf-8").strip(),
                "v1",
            )
            self.assertTrue(
                (root / "vendor" / "inference_realesrgan_video.py").exists()
            )
            self.assertTrue((root / "vendor" / "realesrgan" / "__init__.py").exists())
            self.assertFalse((root / "vendor" / "inference").exists())
            self.assertFalse((root / "vendor" / ".git").exists())

    def test_ensure_backend_force_rebuilds_even_when_revision_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as src:
            root = Path(td)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / ".revision").write_text("v1\n", encoding="utf-8")
            (vendor / "stale.txt").write_text("old", encoding="utf-8")
            src_root = Path(src)
            (src_root / "realesrgan" / "Real-ESRGAN" / "realesrgan").mkdir(parents=True)
            (
                src_root / "realesrgan" / "Real-ESRGAN" / "realesrgan" / "__init__.py"
            ).write_text("pkg", encoding="utf-8")
            spec = BackendSpec(
                root=root,
                backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
                source=SourceSpec(
                    type="git",
                    url="https://example.invalid/realesrgan.git",
                    revision="v1",
                ),
                filter=FilterSpec(
                    include=["realesrgan/Real-ESRGAN/realesrgan/**"], exclude=[]
                ),
                output=OutputSpec(
                    target="vendor",
                    strip_prefixes=["realesrgan/Real-ESRGAN/"],
                ),
            )

            class TempDirStub:
                def __init__(self, name: str) -> None:
                    self.name = name

                def cleanup(self) -> None:
                    return None

            with patch(
                "app.backends.verify.acquire_backend_source",
                return_value=TempDirStub(src),
            ):
                status = ensure_backend(spec, force=True)

            self.assertEqual(status, "rebuilt")
            self.assertFalse((root / "vendor" / "stale.txt").exists())
            self.assertTrue((root / "vendor" / "realesrgan" / "__init__.py").exists())
            self.assertEqual(
                (root / "vendor" / ".revision").read_text(encoding="utf-8").strip(),
                "v1",
            )

    def test_acquire_backend_source_failure_bubbles_up(self) -> None:
        spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
        )
        with patch(
            "app.backends.verify.acquire_backend_source",
            side_effect=RuntimeError("clone failed"),
        ):
            with self.assertRaises(RuntimeError):
                ensure_backend(spec)

    def test_ensure_backend_requires_git_backend_source(self) -> None:
        spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="http", url="https://example.invalid/file.zip", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
        )
        with self.assertRaises(RuntimeError):
            ensure_backend(spec)

    def test_cli_install_runs_backend_rebuild_before_model_ensure(self) -> None:
        from app.backends.cli import main

        backend_spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
        )
        buf = io.StringIO()
        with (
            patch("app.backends.cli.discover", return_value=[backend_spec]),
            patch("app.backends.cli.load_model_specs", return_value=[]),
            patch("app.backends.cli.ensure_backend") as mock_backend_ensure,
            patch("app.backends.cli.ModelManager") as mock_manager_cls,
            contextlib.redirect_stdout(buf),
        ):
            main(["install"])
        mock_backend_ensure.assert_called_once_with(backend_spec)
        mock_manager_cls.return_value.ensure.assert_called_once_with([])
        self.assertIn("ready", buf.getvalue().lower())

    def test_cli_verify_reports_authoritative_backend_rebuild_hint(self) -> None:
        from app.backends.cli import main

        backend_spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
            runtime_inputs=RuntimeInputsSpec(
                root="sources",
                authoritative=True,
                files=["__main__.py", "realesrgan/__init__.py"],
            ),
        )
        buf = io.StringIO()
        with (
            patch("app.backends.cli.discover", return_value=[backend_spec]),
            patch("app.backends.cli.load_model_specs", return_value=[]),
            patch("app.backends.cli.verify_backend") as mock_verify,
            patch("app.backends.cli.ModelManager") as mock_manager_cls,
            self.assertRaises(SystemExit) as ctx,
            contextlib.redirect_stdout(buf),
        ):
            mock_verify.return_value = type(
                "V",
                (),
                {
                    "status": "missing",
                    "missing_files": ["__main__.py", "realesrgan/__init__.py"],
                    "revision": None,
                },
            )()
            mock_manager_cls.return_value.verify.return_value = []
            main(["verify"])
        output = buf.getvalue()
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("backend:realesrgan", output)
        self.assertIn("missing runtime files", output)
        self.assertIn("uv run python -m app.backends install", output)
        self.assertIn("make setup-backends", output)
        self.assertIn("delete third_party/Upscale/realesrgan/vendor", output)

    def test_cli_verify_reports_backend_revision_mismatch(self) -> None:
        from app.backends.cli import main

        backend_spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
        )
        buf = io.StringIO()
        with (
            patch("app.backends.cli.discover", return_value=[backend_spec]),
            patch("app.backends.cli.load_model_specs", return_value=[]),
            patch("app.backends.cli.verify_backend") as mock_verify,
            patch("app.backends.cli.ModelManager") as mock_manager_cls,
            self.assertRaises(SystemExit) as ctx,
            contextlib.redirect_stdout(buf),
        ):
            mock_verify.return_value = type(
                "V",
                (),
                {
                    "status": "mismatch",
                    "missing_files": [],
                    "revision": "old-rev",
                },
            )()
            mock_manager_cls.return_value.verify.return_value = []
            main(["verify"])
        output = buf.getvalue()
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("backend:realesrgan", output)
        self.assertIn("runtime revision old-rev does not match expected v1", output)
        self.assertNotIn("delete third_party/Upscale/realesrgan/vendor", output)

    def test_cli_verify_reports_backend_namespace_when_vendor_missing(self) -> None:
        from app.backends.cli import main

        backend_spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
        )
        buf = io.StringIO()
        with (
            patch("app.backends.cli.discover", return_value=[backend_spec]),
            patch("app.backends.cli.load_model_specs", return_value=[]),
            patch("app.backends.cli.verify_backend") as mock_verify,
            patch("app.backends.cli.ModelManager") as mock_manager_cls,
            self.assertRaises(SystemExit) as ctx,
            contextlib.redirect_stdout(buf),
        ):
            mock_verify.return_value = type(
                "V", (), {"status": "missing", "missing_files": [], "revision": None}
            )()
            mock_manager_cls.return_value.verify.return_value = []
            main(["verify"])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("backend:realesrgan", buf.getvalue())

    def test_cli_rebuild_forces_backend_materialization_before_models(self) -> None:
        from app.backends.cli import main

        backend_spec = BackendSpec(
            root=Path("third_party/Upscale/realesrgan"),
            backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
            source=SourceSpec(
                type="git", url="https://example.invalid/realesrgan.git", revision="v1"
            ),
            filter=FilterSpec(include=["realesrgan/**"], exclude=[]),
            output=OutputSpec(target="vendor", strip_prefixes=[""]),
        )
        buf = io.StringIO()
        with (
            patch("app.backends.cli.discover", return_value=[backend_spec]),
            patch("app.backends.cli.load_model_specs", return_value=[]),
            patch("app.backends.cli.ensure_backend") as mock_backend_ensure,
            patch("app.backends.cli.ModelManager") as mock_manager_cls,
            contextlib.redirect_stdout(buf),
        ):
            main(["rebuild"])
        mock_backend_ensure.assert_called_once_with(backend_spec, force=True)
        mock_manager_cls.return_value.ensure.assert_called_once_with([])
        self.assertIn("rebuild complete", buf.getvalue().lower())
        self.assertIn("ready", buf.getvalue().lower())

    def test_upscale_realesrgan_weights_spec_uses_official_http_artifact(self) -> None:
        env = {
            "MODEL_ROOT": "/models",
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
        realesrgan = next(
            spec
            for spec in discover(Path("third_party/Upscale"))
            if spec.backend.name == "realesrgan"
        )
        self.assertTrue(weights.target_dir.endswith(f"/{realesrgan.weights.family}"))
        self.assertIn(realesrgan.weights.family, weights.target_dir)
        self.assertEqual([f.path for f in weights.files], [realesrgan.weights.filename])
        self.assertTrue(weights.files[0].sha256)
