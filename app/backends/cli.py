import argparse
import sys

from app.settings import settings

from .model_manager import ModelManager
from .model_specs import load_model_specs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backends")
    parser.add_argument("action", choices=["install", "verify", "rebuild", "list"])
    args = parser.parse_args(argv)

    specs = load_model_specs(settings)
    manager = ModelManager()

    if args.action == "install":
        manager.ensure(specs)
        print("Backends and models are ready.")
    elif args.action == "verify":
        missing = manager.verify(specs)
        if missing:
            print(f"Missing: {', '.join(missing)}")
            sys.exit(1)
        print("Backends and models verified.")
    elif args.action == "list":
        for spec in specs:
            print(spec.name)
    elif args.action == "rebuild":
        manager.ensure(specs)
        print("Rebuild complete.")
