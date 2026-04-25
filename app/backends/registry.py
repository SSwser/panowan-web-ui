from pathlib import Path

from .spec import BackendSpec, load_backend_spec


def discover(root: Path) -> list[BackendSpec]:
    specs: list[BackendSpec] = []
    for backend_toml in sorted(root.glob("**/backend.toml")):
        specs.append(load_backend_spec(backend_toml))
    return specs
