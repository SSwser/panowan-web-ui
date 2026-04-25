from pathlib import Path

from app.backends.spec import BackendSpec
from app.backends.registry import discover


def test_discover_reads_backend_toml(tmp_path: Path) -> None:
    backend_dir = tmp_path / "realesrgan"
    backend_dir.mkdir()
    (backend_dir / "backend.toml").write_text(
        """
[backend]
name = "realesrgan"
display_name = "Real-ESRGAN"

[source]
type = "git"
url = "https://example.invalid/realesrgan.git"
revision = "v1"

[filter]
include = ["inference.py"]
exclude = ["**/*.md"]

[output]
target = "vendor"
""".strip(),
        encoding="utf-8",
    )

    specs = discover(tmp_path)
    assert len(specs) == 1
    assert isinstance(specs[0], BackendSpec)
    assert specs[0].backend.name == "realesrgan"
    assert specs[0].source.type == "git"
    assert specs[0].output.target == "vendor"


def test_real_esrgan_backend_toml_exists() -> None:
    root = Path("third_party/Upscale/realesrgan/backend.toml")
    assert root.exists()


def test_real_esrgan_backend_is_discoverable() -> None:
    specs = discover(Path("third_party/Upscale"))
    assert any(spec.backend.name == "realesrgan" for spec in specs)
