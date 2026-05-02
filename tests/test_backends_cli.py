import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from app.backends import cli
from app.backends.cli import _authoritative_rebuild_hint
from app.backends.spec import load_backend_spec


class BackendsCliTests(unittest.TestCase):
    def test_app_backends_module_exists(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app.backends", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("install", result.stdout)
        self.assertIn("verify", result.stdout)
        self.assertIn("rebuild", result.stdout)
        self.assertIn("list", result.stdout)

    def test_authoritative_rebuild_hint_uses_current_workflow_commands(self) -> None:
        hint = _authoritative_rebuild_hint(Path("/tmp/vendor"))

        self.assertIn(".venv/Scripts/python.exe -m app.backends install", hint)
        self.assertIn("make setup", hint)
        self.assertIn("make setup-worktree", hint)
        self.assertNotIn("uv run python -m app.backends install", hint)
        self.assertNotIn("make setup-backends", hint)

    def test_verify_fails_when_panowan_runtime_python_modules_missing(self) -> None:
        panowan_spec = load_backend_spec(Path("third_party/PanoWan/backend.toml"))
        stdout = io.StringIO()

        with (
            patch.object(cli, "discover", return_value=[]),
            patch.object(cli, "verify_backend") as verify_backend,
            patch("app.backends.cli.Path.exists", return_value=True),
            patch.object(cli.ModelManager, "verify", return_value=[]),
            patch("importlib.util.find_spec", side_effect=lambda name: None if name in {"torch", "diffusers", "transformers", "accelerate"} else object()),
            contextlib.redirect_stdout(stdout),
        ):
            verify_backend.return_value = cli.BackendVerification(
                status="ok", missing_files=[], revision=panowan_spec.source.revision
            )
            with self.assertRaises(SystemExit) as exc:
                cli.main(["verify"])

        self.assertEqual(exc.exception.code, 1)
        self.assertIn("Verify failed:", stdout.getvalue())
        self.assertIn("Checkout-local runtime prerequisites:", stdout.getvalue())
        self.assertIn("backend:panowan missing python module: torch", stdout.getvalue())
        self.assertNotIn("Shared model assets:", stdout.getvalue())

    def test_verify_uses_backend_runtime_python_for_python_modules(self) -> None:
        upscale_spec = load_backend_spec(Path("third_party/Upscale/realesrgan/backend.toml"))

        with (
            patch.object(cli, "discover", return_value=[upscale_spec]),
            patch.object(cli, "verify_backend") as verify_backend,
            patch("app.backends.cli.Path.exists", return_value=False),
            patch.object(cli.ModelManager, "verify", return_value=[]),
            patch("importlib.util.find_spec", return_value=None),
            patch("subprocess.run") as subprocess_run,
        ):
            verify_backend.return_value = cli.BackendVerification(
                status="ok", missing_files=[], revision=upscale_spec.source.revision
            )
            subprocess_run.return_value = unittest.mock.Mock(returncode=0)

            cli.main(["verify"])

        subprocess_run.assert_called_once_with(
            [
                upscale_spec.runtime.python,
                "-c",
                "import cv2; import ffmpeg; import tqdm",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )


if __name__ == "__main__":
    unittest.main()
