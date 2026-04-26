from dataclasses import dataclass
from pathlib import Path

from .acquire import acquire_backend_source
from .filter import filter_paths
from .materialize import materialize_backend
from .spec import BackendSpec


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


def expected_backend_files(spec: BackendSpec) -> list[str]:
    if spec.output.expected_files:
        return list(spec.output.expected_files)

    rewritten: list[str] = []
    for path in spec.filter.include:
        target = path[:-3] if path.endswith("/**") else path
        if spec.output.strip_prefixes:
            for prefix in spec.output.strip_prefixes:
                if prefix and target.startswith(prefix):
                    target = target[len(prefix) :]
                    break
        rewritten.append(target)

    if spec.runtime_inputs.files:
        for path in spec.runtime_inputs.files:
            if path not in rewritten:
                rewritten.append(path)
    return rewritten


def ensure_backend(spec: BackendSpec, *, force: bool = False) -> str:
    if spec.source.type != "git":
        raise RuntimeError(
            f"Unsupported backend source type for materialization: {spec.source.type}"
        )

    vendor_dir = spec.root / spec.output.target
    expected_files = expected_backend_files(spec)
    verification = verify_backend(spec.source.revision, vendor_dir, expected_files)
    if verification.status == "ok" and not force:
        return "ok"

    temp_dir = acquire_backend_source(spec)
    try:
        source_root = Path(temp_dir.name)
        all_files = [
            # backend.toml filter patterns are rooted at the transient upstream tree,
            # while runtime inputs live under the backend root. Keeping those inputs
            # separate prevents rebuild from depending on generated vendor state.
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*")
            if path.is_file()
        ]
        filtered = filter_paths(all_files, spec.filter.include, spec.filter.exclude)
        materialize_backend(spec, source_root, filtered)
        return "rebuilt"
    finally:
        temp_dir.cleanup()
