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

[runtime_inputs]
root = "sources"
files = ["inference.py"]
""".strip(),
        encoding="utf-8",
    )

    specs = discover(tmp_path)
    assert len(specs) == 1
    assert isinstance(specs[0], BackendSpec)
    assert specs[0].backend.name == "realesrgan"
    assert specs[0].source.type == "git"
    assert specs[0].output.target == "vendor"
    assert specs[0].output.strip_prefixes is None
    assert specs[0].runtime_inputs.root == "sources"
    assert specs[0].runtime_inputs.files == ["inference.py"]


def test_real_esrgan_backend_toml_exists() -> None:
    root = Path("third_party/Upscale/realesrgan/backend.toml")
    assert root.exists()


def test_real_esrgan_backend_is_discoverable() -> None:
    specs = discover(Path("third_party/Upscale"))
    realesrgan = next(spec for spec in specs if spec.backend.name == "realesrgan")
    assert realesrgan.output.target == "vendor"
    assert realesrgan.output.strip_prefixes == [
        "inference/Real-ESRGAN/",
        "realesrgan/Real-ESRGAN/",
    ]
    assert realesrgan.output.expected_files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/archs/__init__.py",
        "realesrgan/archs/srvgg_arch.py",
    ]
    assert realesrgan.runtime_inputs.root == "sources"
    assert realesrgan.runtime_inputs.files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/archs/__init__.py",
        "realesrgan/archs/srvgg_arch.py",
    ]
