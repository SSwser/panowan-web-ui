from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EngineResult:
    output_path: str
    metadata: dict


class EngineAdapter(Protocol):
    name: str
    capabilities: tuple[str, ...]

    def validate_runtime(self) -> None:
        ...

    def run(self, job: dict) -> EngineResult:
        ...
