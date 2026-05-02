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
        f"rerun `.venv/Scripts/python.exe -m app.backends install`, `make setup`, or `make setup-worktree` to rebuild "
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


def _format_backend_runtime_requirement_failure(
    spec, requirement_type: str, requirement: str
) -> str:
    return (
        f"backend:{spec.backend.name} {requirement_type}: {requirement}"
    )


def _format_verify_failures(
    backend_failures: list[str], runtime_failures: list[str], model_failures: list[str]
) -> str:
    sections: list[str] = []
    if backend_failures:
        sections.append(
            "Backend bundles:\n  - " + "\n  - ".join(backend_failures)
        )
    if runtime_failures:
        sections.append(
            "Checkout-local runtime prerequisites:\n  - "
            + "\n  - ".join(runtime_failures)
        )
    if model_failures:
        sections.append(
            "Shared model assets:\n  - " + "\n  - ".join(model_failures)
        )
    return "Verify failed:\n" + "\n\n".join(sections)


def _verify_backend_runtime_requirements(spec) -> list[str]:
    missing: list[str] = []
    for command in spec.runtime.required_commands or []:
        if shutil.which(command) is None:
            missing.append(
                _format_backend_runtime_requirement_failure(
                    spec, "missing command", command
                )
            )

    required_modules = spec.runtime.required_python_modules or []
    if not required_modules:
        return missing

    runtime_python = spec.runtime.python
    imports = "; ".join(f"import {module_name}" for module_name in required_modules)
    if runtime_python:
        try:
            result = subprocess.run(
                [runtime_python, "-c", imports],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        # Backend metadata may name a container-only interpreter path. Host-side
        # verify still has to prove this checkout can import its runtime stack, so
        # fall back to the current Python when that declared interpreter is absent.
        if result is not None and result.returncode == 0:
            return missing

    for module_name in required_modules:
        if importlib.util.find_spec(module_name) is None:
            missing.append(
                _format_backend_runtime_requirement_failure(
                    spec, "missing python module", module_name
                )
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
        backend_failures: list[str] = []
        runtime_failures: list[str] = []
        for spec in backend_specs:
            verification = verify_backend(
                spec.source.revision,
                spec.root / spec.output.target,
                expected_backend_files(spec),
            )
            if verification.status != "ok":
                backend_failures.append(
                    _format_backend_verification_failure(spec, verification)
                )
                continue
            # Worktrees reuse shared model data, but each checkout still owns its
            # local runtime readiness, so verify must fail until this checkout can
            # actually import and execute the backend stack it depends on.
            runtime_failures.extend(_verify_backend_runtime_requirements(spec))
        model_failures = manager.verify(model_specs)
        if backend_failures or runtime_failures or model_failures:
            print(
                _format_verify_failures(
                    backend_failures, runtime_failures, model_failures
                )
            )
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
