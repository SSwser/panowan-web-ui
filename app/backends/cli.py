import argparse
import sys
from pathlib import Path

from app.settings import settings

from .model_manager import ModelManager
from .model_specs import load_model_specs
from .registry import discover
from .verify import ensure_backend, expected_backend_files, verify_backend


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backends")
    parser.add_argument("action", choices=["install", "verify", "rebuild", "list"])
    args = parser.parse_args(argv)

    backend_specs = discover(Path(settings.upscale_engine_dir))
    model_specs = load_model_specs(settings)
    manager = ModelManager()

    if args.action == "install":
        for spec in backend_specs:
            ensure_backend(spec)
        manager.ensure(model_specs)
        print("Backends and models are ready.")
    elif args.action == "verify":
        missing = []
        for spec in backend_specs:
            verification = verify_backend(
                spec.source.revision,
                spec.root / spec.output.target,
                expected_backend_files(spec),
            )
            if verification.status != "ok":
                missing.append(f"backend:{spec.backend.name}")
        missing.extend(manager.verify(model_specs))
        if missing:
            print(f"Missing: {', '.join(missing)}")
            sys.exit(1)
        print("Backends and models verified.")
    elif args.action == "list":
        for spec in backend_specs:
            print(f"backend:{spec.backend.name}")
        for spec in model_specs:
            print(spec.name)
    elif args.action == "rebuild":
        for spec in backend_specs:
            ensure_backend(spec, force=True)
        print("Rebuild complete.")
        manager.ensure(model_specs)
        print("Backends and models are ready.")


if __name__ == "__main__":
    main()
