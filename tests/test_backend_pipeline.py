from pathlib import Path

from app.backends.filter import filter_paths
from app.backends.materialize import write_revision
from app.backends.verify import verify_backend


def test_filter_paths_applies_include_and_exclude() -> None:
    paths = [
        "inference.py",
        "README.md",
        "realesrgan/model.py",
        "realesrgan/test_model.py",
    ]
    filtered = filter_paths(
        paths,
        include=["inference.py", "realesrgan/**"],
        exclude=["**/*.md", "realesrgan/**/test*"],
    )
    assert filtered == ["inference.py", "realesrgan/model.py"]


def test_write_revision_creates_marker(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    write_revision(vendor_dir, "v0.3.0")
    assert (vendor_dir / ".revision").read_text(encoding="utf-8") == "v0.3.0\n"


def test_verify_backend_reports_missing_revision(tmp_path: Path) -> None:
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    result = verify_backend(
        expected_revision="v0.3.0", vendor_dir=vendor_dir, expected_files=["a.py"]
    )
    assert result.status == "missing"
