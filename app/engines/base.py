from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EngineResult:
    output_path: str
    metadata: dict = field(default_factory=dict)


class EngineAdapter(Protocol):
    name: str
    capabilities: tuple[str, ...]

    def validate_runtime(self) -> None: ...

    def run(self, job: dict) -> EngineResult: ...
