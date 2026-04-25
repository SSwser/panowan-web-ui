import hashlib
import os
from typing import Protocol

from .registry import ModelSpec

try:
    from huggingface_hub import snapshot_download
except ImportError:  # pragma: no cover
    snapshot_download = None  # type: ignore[assignment]


class ModelProvider(Protocol):
    def ensure(self, spec: ModelSpec) -> None: ...
    def verify(self, spec: ModelSpec) -> None: ...


def _check_sha256(path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest() == expected


class HuggingFaceProvider:
    """Downloads model assets from Hugging Face Hub."""

    def _all_files_present(self, spec: ModelSpec) -> bool:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.isfile(full_path):
                return False
            if f.sha256 and not _check_sha256(full_path, f.sha256):
                return False
        return True

    def verify(self, spec: ModelSpec) -> None:
        for f in spec.files:
            full_path = os.path.join(spec.target_dir, f.path)
            if not os.path.isfile(full_path):
                raise FileNotFoundError(
                    f"Missing model file: {full_path} (spec: {spec.name})"
                )
            if f.sha256 and not _check_sha256(full_path, f.sha256):
                raise RuntimeError(f"Hash mismatch for {full_path} (spec: {spec.name})")

    def ensure(self, spec: ModelSpec) -> None:
        if self._all_files_present(spec):
            return
        if snapshot_download is None:
            raise RuntimeError(
                f"huggingface_hub is not installed; install it with `pip install huggingface_hub` "
                f"to enable downloading {spec.name} from {spec.source_ref}"
            )
        # Note: revision is not pinned; integrity is enforced via FileCheck.sha256 when set.
        snapshot_download(
            repo_id=spec.source_ref,
            local_dir=spec.target_dir,
        )
        if not self._all_files_present(spec):
            raise RuntimeError(
                f"Download completed but files still missing for {spec.name}"
            )


class SubmoduleProvider:
    """Validates third_party-backed assets that are built into the image."""

    def _require_present(self, spec: ModelSpec) -> None:
        for file_check in spec.files:
            full_path = os.path.join(spec.target_dir, file_check.path)
            if not os.path.exists(full_path):
                raise FileNotFoundError(
                    f"Submodule artifact missing: {full_path}. "
                    f"This should be included in the Docker image via third_party/."
                )

    def ensure(self, spec: ModelSpec) -> None:
        self._require_present(spec)

    def verify(self, spec: ModelSpec) -> None:
        self._require_present(spec)
