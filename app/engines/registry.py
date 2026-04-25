from .base import EngineAdapter


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, EngineAdapter] = {}

    def register(self, engine: EngineAdapter) -> None:
        if engine.name in self._engines:
            raise ValueError(f"Engine already registered: {engine.name}")
        self._engines[engine.name] = engine

    def get(self, name: str) -> EngineAdapter:
        if name not in self._engines:
            raise KeyError(f"Unknown engine: {name}")
        return self._engines[name]

    def all(self) -> tuple[EngineAdapter, ...]:
        return tuple(self._engines.values())
