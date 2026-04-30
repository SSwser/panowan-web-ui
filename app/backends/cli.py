import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from app.settings import settings

from .model_manager import ModelManager
from .model_specs import load_model_specs
from .registry import discover
from .spec import load_backend_spec
from .verify import (
    BackendVerification,
    ensure_backend,
    expected_backend_files,
    verify_backend,
)


def _format_missing_files(missing_files: list[str]) -> str:
    preview = ", ".join(missing_files[:3])
    if len(missing_files) > 3:
        preview = f"{preview}, ..."
    return preview


def _authoritative_rebuild_hint(vendor_dir: Path) -> str:
    return (
        f"rerun `uv run python -m app.backends install` or `make setup-backends` to rebuild "
        f"{vendor_dir.as_posix()}; if verification is blocked by directory stat limitations, "
        f"delete {vendor_dir.as_posix()} and rerun install"
    )


def _format_backend_verification_failure(
    spec, verification: BackendVerification
) -> str:
    vendor_dir = spec.root / spec.output.target
    details = [f"backend:{spec.backend.name}"]
    if verification.status == "mismatch":
        details.append(
            f"runtime revision {verification.revision or 'unknown'} does not match expected {spec.source.revision}"
        )
    elif verification.missing_files:
        details.append(
            f"missing runtime files: {_format_missing_files(verification.missing_files)}"
        )
    else:
        details.append(f"runtime bundle missing at {vendor_dir.as_posix()}")

    if spec.runtime_inputs.authoritative:
        # Authoritative runtime inputs make vendor disposable derived state, so a
        # rebuild hint is more actionable than a generic missing-files label.
        details.append(_authoritative_rebuild_hint(vendor_dir))
    return " — ".join(details)


def _verify_backend_runtime_requirements(spec) -> list[str]:
    missing: list[str] = []
    for command in spec.runtime.required_commands or []:
        if shutil.which(command) is None:
            missing.append(f"backend:{spec.backend.name} missing command: {command}")

    required_modules = spec.runtime.required_python_modules or []
    if not required_modules:
        return missing

    runtime_python = spec.runtime.python
    if runtime_python:
        imports = "; ".join(f"import {module_name}" for module_name in required_modules)
        try:
            result = subprocess.run(
                [runtime_python, "-c", imports],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is None or result.returncode != 0:
            for module_name in required_modules:
                missing.append(
                    f"backend:{spec.backend.name} missing python module: {module_name}"
                )
        return missing

    for module_name in required_modules:
        if importlib.util.find_spec(module_name) is None:
            missing.append(
                f"backend:{spec.backend.name} missing python module: {module_name}"
            )
    return missing


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backends")
    parser.add_argument("action", choices=["install", "verify", "rebuild", "list"])
    args = parser.parse_args(argv)

    backend_specs = discover(Path(settings.upscale_engine_dir))
    # PanoWan lives at a fixed path (panowan_engine_dir/backend.toml) rather than
    # inside the upscale engine tree, so discover() never finds it. Load it
    # explicitly so install/verify/rebuild apply to both engine families.
    panowan_toml = Path(settings.panowan_engine_dir) / "backend.toml"
    if panowan_toml.exists():
        backend_specs = [load_backend_spec(panowan_toml)] + backend_specs
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
                missing.append(_format_backend_verification_failure(spec, verification))
                continue
            missing.extend(_verify_backend_runtime_requirements(spec))
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
