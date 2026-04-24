from .base import EngineAdapter


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, EngineAdapter] = {}

    def register(self, engine: EngineAdapter) -> None:
        self._engines[engine.name] = engine

    def get(self, name: str) -> EngineAdapter:
        if name not in self._engines:
            raise KeyError(f"Unknown engine: {name}")
        return self._engines[name]
