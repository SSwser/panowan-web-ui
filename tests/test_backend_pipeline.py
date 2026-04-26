from pathlib import Path

from app.backends.filter import filter_paths
from app.backends.materialize import write_revision
from app.backends.spec import BackendSection, BackendSpec, OutputSpec, RuntimeInputsSpec, SourceSpec
from app.backends.verify import BackendVerification, verify_backend


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


def test_authoritative_backend_missing_files_are_reported_for_rebuild_hint() -> None:
    from app.backends.cli import _format_backend_verification_failure

    spec = BackendSpec(
        root=Path("third_party/Upscale/realesrgan"),
        backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
        source=SourceSpec(type="git", url="https://example.invalid/realesrgan.git", revision="v1"),
        output=OutputSpec(target="vendor"),
        runtime_inputs=RuntimeInputsSpec(
            root="sources",
            authoritative=True,
            files=["__main__.py", "realesrgan/__init__.py"],
        ),
    )
    verification = BackendVerification(
        status="missing",
        missing_files=["__main__.py", "realesrgan/__init__.py"],
        revision=None,
    )

    message = _format_backend_verification_failure(spec, verification)

    assert "backend:realesrgan" in message
    assert "missing runtime files: __main__.py, realesrgan/__init__.py" in message
    assert "uv run -m app.backends install" in message
    assert "make setup-backends" in message
    assert "delete third_party/Upscale/realesrgan/vendor" in message


def test_non_authoritative_backend_mismatch_skips_delete_vendor_hint() -> None:
    from app.backends.cli import _format_backend_verification_failure

    spec = BackendSpec(
        root=Path("third_party/Upscale/realesrgan"),
        backend=BackendSection(name="realesrgan", display_name="Real-ESRGAN"),
        source=SourceSpec(type="git", url="https://example.invalid/realesrgan.git", revision="v1"),
        output=OutputSpec(target="vendor"),
    )
    verification = BackendVerification(
        status="mismatch",
        missing_files=[],
        revision="old-rev",
    )

    message = _format_backend_verification_failure(spec, verification)

    assert "runtime revision old-rev does not match expected v1" in message
    assert "delete third_party/Upscale/realesrgan/vendor" not in message
    assert "uv run -m app.backends install" not in message
