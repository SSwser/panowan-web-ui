import argparse
import sys

from app.settings import load_settings

from .manager import ModelManager
from .specs import load_specs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Model asset manager")
    parser.add_argument("action", choices=["ensure", "verify"])
    args = parser.parse_args(argv)

    specs = load_specs(load_settings())
    manager = ModelManager()

    if args.action == "ensure":
        manager.ensure(specs)
        print("All model assets ready.")
    elif args.action == "verify":
        missing = manager.verify(specs)
        if missing:
            print(f"Missing: {', '.join(missing)}")
            print("Run: make setup-models")
            sys.exit(1)
        print("All model assets verified.")


if __name__ == "__main__":
    main()
