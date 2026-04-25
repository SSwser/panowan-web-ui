from .model_spec import ModelSpec
from .providers import HuggingFaceProvider, HttpProvider, SubmoduleProvider


class ModelManager:
    def __init__(self) -> None:
        self._providers = {
            "huggingface": HuggingFaceProvider(),
            "submodule": SubmoduleProvider(),
            "http": HttpProvider(),
        }

    def ensure(self, specs: list[ModelSpec]) -> None:
        for spec in specs:
            provider = self._providers.get(spec.source_type)
            if provider is None:
                raise ValueError(f"Unknown source_type: {spec.source_type}")
            provider.ensure(spec)

    def verify(self, specs: list[ModelSpec]) -> list[str]:
        missing = []
        for spec in specs:
            provider = self._providers.get(spec.source_type)
            if provider is None:
                missing.append(spec.name)
                continue
            try:
                provider.verify(spec)
            except (FileNotFoundError, RuntimeError):
                missing.append(spec.name)
        return missing
