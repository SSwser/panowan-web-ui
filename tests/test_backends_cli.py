import subprocess
import sys


def test_app_backends_module_exists() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.backends", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "install" in result.stdout
    assert "verify" in result.stdout
    assert "rebuild" in result.stdout
    assert "list" in result.stdout
