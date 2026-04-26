from dataclasses import dataclass, field
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
    strip_prefixes: list[str] | None = None
    expected_files: list[str] | None = None


@dataclass(frozen=True)
class RuntimeInputsSpec:
    root: str = "sources"
    files: list[str] | None = None


@dataclass(frozen=True)
class BackendSpec:
    root: Path
    backend: BackendSection
    source: SourceSpec
    filter: FilterSpec
    output: OutputSpec
    runtime_inputs: RuntimeInputsSpec = field(default_factory=RuntimeInputsSpec)

    # Backend specs in tests often only care about the acquisition/materialization
    # contract, so runtime input metadata should stay optional unless a test exercises it.


def load_backend_spec(path: Path) -> BackendSpec:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    output_data = dict(data.get("output", {}))
    strip_prefixes = output_data.get("strip_prefixes")
    if strip_prefixes is not None:
        output_data["strip_prefixes"] = list(strip_prefixes)
    expected_files = output_data.get("expected_files")
    if expected_files is not None:
        output_data["expected_files"] = list(expected_files)
    runtime_inputs_data = dict(data.get("runtime_inputs", {}))
    runtime_input_files = runtime_inputs_data.get("files")
    if runtime_input_files is not None:
        runtime_inputs_data["files"] = list(runtime_input_files)
    return BackendSpec(
        root=path.parent,
        backend=BackendSection(**data["backend"]),
        source=SourceSpec(**data["source"]),
        filter=FilterSpec(
            include=list(data.get("filter", {}).get("include", [])),
            exclude=list(data.get("filter", {}).get("exclude", [])),
        ),
        output=OutputSpec(**output_data),
        runtime_inputs=RuntimeInputsSpec(**runtime_inputs_data),
    )
