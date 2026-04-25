from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class BackendSection:
    name: str
    display_name: str


@dataclass(frozen=True)
class SourceSpec:
    type: str
    url: str
    revision: str


@dataclass(frozen=True)
class FilterSpec:
    include: list[str]
    exclude: list[str]


@dataclass(frozen=True)
class OutputSpec:
    target: str = "vendor"


@dataclass(frozen=True)
class BackendSpec:
    root: Path
    backend: BackendSection
    source: SourceSpec
    filter: FilterSpec
    output: OutputSpec


def load_backend_spec(path: Path) -> BackendSpec:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return BackendSpec(
        root=path.parent,
        backend=BackendSection(**data["backend"]),
        source=SourceSpec(**data["source"]),
        filter=FilterSpec(
            include=list(data.get("filter", {}).get("include", [])),
            exclude=list(data.get("filter", {}).get("exclude", [])),
        ),
        output=OutputSpec(**data.get("output", {})),
    )
