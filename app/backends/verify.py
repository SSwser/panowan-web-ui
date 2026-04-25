from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendVerification:
    status: str
    missing_files: list[str]
    revision: str | None


def verify_backend(
    expected_revision: str, vendor_dir: Path, expected_files: list[str]
) -> BackendVerification:
    revision_path = vendor_dir / ".revision"
    if not revision_path.exists():
        return BackendVerification(
            status="missing", missing_files=expected_files, revision=None
        )
    actual_revision = revision_path.read_text(encoding="utf-8").strip()
    if actual_revision != expected_revision:
        return BackendVerification(
            status="mismatch", missing_files=expected_files, revision=actual_revision
        )
    missing = [name for name in expected_files if not (vendor_dir / name).exists()]
    return BackendVerification(
        status="ok" if not missing else "missing",
        missing_files=missing,
        revision=actual_revision,
    )
