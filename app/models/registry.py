from dataclasses import dataclass


@dataclass(frozen=True)
class FileCheck:
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    source_type: str
    source_ref: str
    target_dir: str
    files: list[FileCheck]
