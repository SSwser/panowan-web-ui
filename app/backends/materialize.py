import shutil
from pathlib import Path

from .spec import BackendSpec


def _rewrite_relative_path(path: str, strip_prefixes: list[str] | None) -> str:
    if not strip_prefixes:
        return path
    for prefix in strip_prefixes:
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def write_revision(vendor_dir: Path, revision: str) -> None:
    (vendor_dir / ".revision").write_text(f"{revision}\n", encoding="utf-8")


def _copy_file(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def materialize_backend(
    spec: BackendSpec, source_root: Path | None, relative_paths: list[str]
) -> Path:
    vendor_dir = spec.root / spec.output.target
    if vendor_dir.exists():
        shutil.rmtree(vendor_dir)
    vendor_dir.mkdir(parents=True, exist_ok=True)

    if spec.runtime_inputs.authoritative:
        runtime_inputs_root = spec.root / spec.runtime_inputs.root
        if spec.runtime_inputs.files:
            for relative_path in spec.runtime_inputs.files:
                _copy_file(runtime_inputs_root / relative_path, vendor_dir / relative_path)
    else:
        if source_root is None:
            raise RuntimeError(
                "source_root is required for non-authoritative runtime materialization"
            )
        for relative_path in relative_paths:
            source_path = source_root / relative_path
            target_relative = _rewrite_relative_path(
                relative_path, spec.output.strip_prefixes
            )
            _copy_file(source_path, vendor_dir / target_relative)

        if spec.runtime_inputs.files:
            runtime_inputs_root = spec.root / spec.runtime_inputs.root
            for relative_path in spec.runtime_inputs.files:
                _copy_file(runtime_inputs_root / relative_path, vendor_dir / relative_path)

    write_revision(vendor_dir, spec.source.revision)
    return vendor_dir
