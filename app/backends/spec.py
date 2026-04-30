import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
    authoritative: bool = False


@dataclass(frozen=True)
class RuntimeSpec:
    python: str | None = None
    required_commands: list[str] | None = None
    required_python_modules: list[str] | None = None


@dataclass(frozen=True)
class WeightsSpec:
    family: str | None = None
    filename: str | None = None
    required_files: list[str] | None = None


@dataclass(frozen=True)
class ResidentProviderSpec:
    enabled: bool = False
    provider_key: str | None = None
    entrypoint_module: str | None = None
    load_attr: str | None = None
    execute_attr: str | None = None
    teardown_attr: str | None = None
    identity_attr: str | None = None
    failure_classifier_attr: str | None = None
    startup_preload: bool = False
    idle_evict_seconds: float | None = None
    resource_class: str | None = None


@dataclass(frozen=True)
class BackendSpec:
    root: Path
    backend: BackendSection
    source: SourceSpec
    filter: FilterSpec
    output: OutputSpec
    runtime_inputs: RuntimeInputsSpec = field(default_factory=RuntimeInputsSpec)
    runtime: RuntimeSpec = field(default_factory=RuntimeSpec)
    weights: WeightsSpec = field(default_factory=WeightsSpec)
    resident_provider: ResidentProviderSpec = field(
        default_factory=ResidentProviderSpec
    )

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
    authoritative = runtime_inputs_data.get("authoritative")
    if authoritative is not None:
        runtime_inputs_data["authoritative"] = bool(authoritative)

    runtime_data = dict(data.get("runtime", {}))
    required_commands = runtime_data.get("required_commands")
    if required_commands is not None:
        runtime_data["required_commands"] = list(required_commands)
    required_python_modules = runtime_data.get("required_python_modules")
    if required_python_modules is not None:
        runtime_data["required_python_modules"] = list(required_python_modules)

    weights_data = dict(data.get("weights", {}))
    required_files = weights_data.get("required_files")
    if required_files is not None:
        weights_data["required_files"] = list(required_files)

    resident_provider_data = dict(data.get("resident_provider", {}))
    if "enabled" in resident_provider_data:
        resident_provider_data["enabled"] = bool(resident_provider_data["enabled"])
    if "startup_preload" in resident_provider_data:
        resident_provider_data["startup_preload"] = bool(
            resident_provider_data["startup_preload"]
        )
    if resident_provider_data.get("idle_evict_seconds") is not None:
        resident_provider_data["idle_evict_seconds"] = float(
            resident_provider_data["idle_evict_seconds"]
        )

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
        runtime=RuntimeSpec(**runtime_data),
        weights=WeightsSpec(**weights_data),
        resident_provider=ResidentProviderSpec(**resident_provider_data),
    )
