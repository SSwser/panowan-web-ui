from pathlib import Path

from .spec import BackendSpec, load_backend_spec


def discover(root: Path) -> list[BackendSpec]:
    specs: list[BackendSpec] = []
    # Single-level glob avoids inadvertently traversing vendor/, .tmp/, or build/
    # subdirectories that could be large or contain unexpected backend.toml files.
    for backend_toml in sorted(root.glob("*/backend.toml")):
        specs.append(load_backend_spec(backend_toml))
    return specs
