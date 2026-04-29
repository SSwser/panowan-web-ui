from pathlib import Path

from app.backends.registry import discover
from app.backends.spec import BackendSpec
from app.upscaler import _load_realesrgan_backend_spec


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
    assert specs[0].runtime_inputs.authoritative is False
    assert specs[0].runtime_inputs.files == ["inference.py"]
    assert specs[0].runtime.python is None
    assert specs[0].runtime.required_commands is None
    assert specs[0].runtime.required_python_modules is None
    assert specs[0].weights.family is None
    assert specs[0].weights.filename is None
    assert specs[0].weights.required_files is None


def test_real_esrgan_backend_toml_exists() -> None:
    root = Path("third_party/Upscale/realesrgan/backend.toml")
    assert root.exists()


def test_real_esrgan_backend_is_discoverable() -> None:
    specs = discover(Path("third_party/Upscale"))
    realesrgan = next(spec for spec in specs if spec.backend.name == "realesrgan")
    assert realesrgan.output.target == "vendor"
    assert realesrgan.output.strip_prefixes is None
    assert realesrgan.output.expected_files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/srvgg_arch.py",
    ]
    assert realesrgan.runtime_inputs.root == "sources"
    assert realesrgan.runtime_inputs.authoritative is True
    assert realesrgan.runtime_inputs.files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/srvgg_arch.py",
    ]
    assert realesrgan.runtime.python == "/opt/venvs/upscale-realesrgan/bin/python"
    assert realesrgan.runtime.required_commands == ["ffmpeg"]
    assert realesrgan.runtime.required_python_modules == ["cv2", "ffmpeg", "tqdm"]
    assert realesrgan.weights.family == "Real-ESRGAN"
    assert realesrgan.weights.filename == "realesr-animevideov3.pth"
    assert realesrgan.weights.required_files == [
        "Real-ESRGAN/realesr-animevideov3.pth"
    ]


def _assert_realesrgan_spec(realesrgan: BackendSpec, backend_dir: Path) -> None:
    assert realesrgan.root == backend_dir
    assert realesrgan.backend.name == "realesrgan"
    assert realesrgan.backend.display_name == "Real-ESRGAN"
    assert realesrgan.source.type == "git"
    assert realesrgan.source.url == "https://github.com/xinntao/Real-ESRGAN.git"
    assert realesrgan.source.revision == "v0.3.0"
    assert realesrgan.filter.include == []
    assert realesrgan.filter.exclude == []
    assert realesrgan.output.target == "vendor"
    assert realesrgan.output.strip_prefixes is None
    assert realesrgan.output.expected_files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/srvgg_arch.py",
    ]
    assert realesrgan.runtime_inputs.root == "sources"
    assert realesrgan.runtime_inputs.authoritative is True
    assert realesrgan.runtime_inputs.files == [
        "__main__.py",
        "inference_realesrgan_video.py",
        "realesrgan/__init__.py",
        "realesrgan/utils.py",
        "realesrgan/srvgg_arch.py",
    ]
    assert realesrgan.runtime.python == "/opt/venvs/upscale-realesrgan/bin/python"
    assert realesrgan.runtime.required_commands == ["ffmpeg"]
    assert realesrgan.runtime.required_python_modules == ["cv2", "ffmpeg", "tqdm"]
    assert realesrgan.weights.family == "Real-ESRGAN"
    assert realesrgan.weights.filename == "realesr-animevideov3.pth"
    assert realesrgan.weights.required_files == ["Real-ESRGAN/realesr-animevideov3.pth"]
    assert realesrgan.root.exists()


def test_load_realesrgan_backend_spec_accepts_runtime_backend_root(tmp_path: Path) -> None:
    backend_dir = tmp_path / "realesrgan"
    backend_dir.mkdir()
    (backend_dir / "backend.toml").write_text(
        Path("third_party/Upscale/realesrgan/backend.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    realesrgan = _load_realesrgan_backend_spec(tmp_path)

    _assert_realesrgan_spec(realesrgan, backend_dir)


def test_upscaler_module_registers_realesrgan_backend_without_eager_assets() -> None:
    import app.upscaler as upscaler_module

    backend = upscaler_module.UPSCALE_BACKENDS["realesrgan-animevideov3"]

    assert backend.display_name == "Real-ESRGAN (Fast)"
    assert backend.default_scale == 2
    assert backend.max_scale == 4
    assert callable(type(backend).assets.fget)
