import subprocess
import sys
import unittest
from pathlib import Path

from app.backends.cli import _authoritative_rebuild_hint


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

    def test_authoritative_rebuild_hint_uses_valid_uv_python_command(self) -> None:
        hint = _authoritative_rebuild_hint(Path("/tmp/vendor"))

        self.assertIn("uv run python -m app.backends install", hint)
        self.assertNotIn("uv run -m app.backends install", hint)


if __name__ == "__main__":
    unittest.main()
