"""Upscaler module: Protocol-based backend registry for video upscaling."""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.backends.registry import discover
from app.backends.verify import expected_backend_files
from app.cancellation import RuntimeCancellationProbe
from app.paths import container_join, default_runtime_roots, repo_root_from
from app.process_runner import (
    ProcessCancelledError,
    output_tail,
    run_cancellable_process,
)


@dataclass(frozen=True)
class UpscaleBackendAssets:
    """Files, commands, and Python runtime a backend needs to be available."""

    engine_files: tuple[str, ...]
    weight_files: tuple[str, ...]
    required_commands: tuple[str, ...] = ()
    runtime_python: str | None = None
    required_python_modules: tuple[str, ...] = ()


@runtime_checkable
class UpscalerBackend(Protocol):
    """Protocol defining the interface for an upscaler backend."""

    name: str
    display_name: str
    default_scale: int
    max_scale: int
    assets: UpscaleBackendAssets

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        engine_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]: ...

    def validate_params(
        self,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> str | None: ...


def _load_realesrgan_backend_spec(backend_root: Path | None = None):
    repo_root = repo_root_from(__file__)
    runtime_backend_root = Path(
        default_runtime_roots(repo_root=repo_root, in_container=os.path.isfile("/.dockerenv"))
        .upscale_engine_root
    )
    candidate_roots = [backend_root or runtime_backend_root, Path(repo_root) / "third_party" / "Upscale"]
    seen: set[Path] = set()
    for candidate_root in candidate_roots:
        resolved_root = Path(candidate_root)
        if resolved_root in seen:
            continue
        seen.add(resolved_root)
        spec = next(
            (spec for spec in discover(resolved_root) if spec.backend.name == "realesrgan"),
            None,
        )
        if spec is not None:
            return spec
    raise RuntimeError("Backend spec realesrgan not found in configured backend roots")


# API process can start without mounted upscale runtime assets, so backend spec
# lookup falls back to repo metadata until runtime validation checks real engine roots.


def _build_realesrgan_assets() -> UpscaleBackendAssets:
    spec = _load_realesrgan_backend_spec()
    vendor_files = [f"realesrgan/{spec.output.target}/{path}" for path in expected_backend_files(spec)]
    return UpscaleBackendAssets(
        engine_files=tuple(["realesrgan/runner.py", *vendor_files]),
        weight_files=tuple(spec.weights.required_files or ()),
        required_commands=tuple(spec.runtime.required_commands or ()),
        runtime_python=spec.runtime.python,
        required_python_modules=tuple(spec.runtime.required_python_modules or ()),
    )


class RealESRGANBackend:
    """Real-ESRGAN anime video upscaler backend (fast)."""

    name: str = "realesrgan-animevideov3"
    display_name: str = "Real-ESRGAN (Fast)"
    default_scale: int = 2
    max_scale: int = 4

    @property
    def assets(self) -> UpscaleBackendAssets:
        return _build_realesrgan_assets()

    @property
    def weight_family(self) -> str:
        spec = _load_realesrgan_backend_spec()
        if spec.weights.family is None:
            raise RuntimeError("Backend spec realesrgan missing weights.family")
        return spec.weights.family

    @property
    def weight_filename(self) -> str:
        spec = _load_realesrgan_backend_spec()
        if spec.weights.filename is None:
            raise RuntimeError("Backend spec realesrgan missing weights.filename")
        return spec.weights.filename

    @property
    def runtime_python(self) -> str:
        return self.assets.runtime_python or sys.executable

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        engine_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        spec = _load_realesrgan_backend_spec(Path(engine_dir))
        if spec.weights.family is None:
            raise RuntimeError("Backend spec realesrgan missing weights.family")
        if spec.weights.filename is None:
            raise RuntimeError("Backend spec realesrgan missing weights.filename")
        if spec.runtime.python is None:
            raise RuntimeError("Backend spec realesrgan missing runtime.python")
        # Runtime jobs must enter through backend-root integration code so the
        # stable project-owned entrypoint survives vendor/ rebuilds without
        # changing command construction or availability checks.
        script = container_join(engine_dir, "realesrgan", "runner.py")
        model_path = container_join(weights_dir, spec.weights.family, spec.weights.filename)
        return [
            spec.runtime.python,
            script,
            "-i",
            input_path,
            "-o",
            output_dir,
            "-n",
            "realesr-animevideov3",
            "--model_path",
            model_path,
            "-s",
            str(scale),
        ]

    def validate_params(
        self,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> str | None:
        if target_width is not None or target_height is not None:
            return f"{self.display_name} does not support target_width/target_height overrides"
        if scale > self.max_scale:
            return (
                f"Scale {scale} exceeds maximum {self.max_scale} "
                f"for {self.display_name}"
            )
        return None


class RealBasicVSRBackend:
    """RealBasicVSR upscaler backend (high quality, 4x only)."""

    name: str = "realbasicvsr"
    display_name: str = "RealBasicVSR (High Quality)"
    default_scale: int = 4
    max_scale: int = 4
    assets: UpscaleBackendAssets = UpscaleBackendAssets(
        engine_files=(
            "realbasicvsr/adapter.py",
            "realbasicvsr/configs/realbasicvsr_x4.py",
        ),
        weight_files=("realbasicvsr/RealBasicVSR_x4.pth",),
    )

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        engine_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        backend_dir = container_join(engine_dir, "realbasicvsr")
        script = container_join(backend_dir, "inference_realbasicvsr.py")
        config = container_join(backend_dir, "configs", "realbasicvsr_x4.py")
        checkpoint = container_join(weights_dir, "realbasicvsr", "RealBasicVSR_x4.pth")
        output_path = container_join(output_dir, "output.mp4")
        return [
            sys.executable,
            script,
            config,
            checkpoint,
            input_path,
            output_path,
            "--max-seq-len",
            "30",
        ]

    def validate_params(
        self,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> str | None:
        if scale != 4:
            return (
                f"{self.display_name} only supports 4x upscaling, " f"got scale={scale}"
            )
        return None


class SeedVR2Backend:
    """SeedVR2-3B upscaler backend (state-of-the-art)."""

    name: str = "seedvr2-3b"
    display_name: str = "SeedVR2-3B (SOTA)"
    default_scale: int = 2
    max_scale: int = 4
    assets: UpscaleBackendAssets = UpscaleBackendAssets(
        engine_files=("seedvr2/projects/inference_seedvr2_3b.py",),
        weight_files=(
            "seedvr2/seedvr2_ema_3b.pth",
            "seedvr2/ema_vae.pth",
            "seedvr2/pos_emb.pt",
            "seedvr2/neg_emb.pt",
        ),
        required_commands=("torchrun",),
    )

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        engine_dir: str,
        weights_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        script = container_join(
            engine_dir, "seedvr2", "projects", "inference_seedvr2_3b.py"
        )
        input_dir = os.path.dirname(input_path)
        res_w = str(target_width) if target_width else "896"
        res_h = str(target_height) if target_height else "448"
        return [
            "torchrun",
            "--nproc_per_node=1",
            script,
            "--video_path",
            input_dir,
            "--output_dir",
            output_dir,
            "--res_h",
            res_h,
            "--res_w",
            res_w,
            "--sp_size",
            "1",
        ]

    def validate_params(
        self,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> str | None:
        if scale > self.max_scale:
            return (
                f"Scale {scale} exceeds maximum {self.max_scale} "
                f"for {self.display_name}"
            )
        if target_width is not None and target_width % 32 != 0:
            return (
                f"Target width {target_width} is not a multiple of 32 "
                f"for {self.display_name}"
            )
        if target_height is not None and target_height % 32 != 0:
            return (
                f"Target height {target_height} is not a multiple of 32 "
                f"for {self.display_name}"
            )
        return None


UPSCALE_BACKENDS: dict[str, UpscalerBackend] = {
    "realesrgan-animevideov3": RealESRGANBackend(),
    "realbasicvsr": RealBasicVSRBackend(),
    "seedvr2-3b": SeedVR2Backend(),
}


def _has_backend_runtime(backend: UpscalerBackend) -> bool:
    if backend.assets.runtime_python is None:
        return True
    if not os.path.exists(backend.assets.runtime_python):
        return False
    if not backend.assets.required_python_modules:
        return True

    imports = "; ".join(
        f"import {module_name}"
        for module_name in backend.assets.required_python_modules
    )
    try:
        result = subprocess.run(
            [backend.assets.runtime_python, "-c", imports],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _has_backend_assets(
    backend: UpscalerBackend,
    engine_dir: str,
    weights_dir: str,
) -> bool:
    for relative_path in backend.assets.engine_files:
        if not os.path.exists(container_join(engine_dir, relative_path)):
            return False
    for relative_path in backend.assets.weight_files:
        if not os.path.exists(container_join(weights_dir, relative_path)):
            return False
    for command in backend.assets.required_commands:
        if shutil.which(command) is None:
            return False
    if not _has_backend_runtime(backend):
        return False
    return True


def get_available_upscale_backends(
    engine_dir: str,
    weights_dir: str,
    backends: Mapping[str, UpscalerBackend] = UPSCALE_BACKENDS,
) -> dict[str, UpscalerBackend]:
    """Return registered backends whose declared assets/commands are present."""
    return {
        name: backend
        for name, backend in backends.items()
        if _has_backend_assets(backend, engine_dir, weights_dir)
    }


def _list_files(directory: str) -> set[str]:
    try:
        return {
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, name))
        }
    except FileNotFoundError:
        return set()


def _expected_realesrgan_output_path(input_path: str, output_dir: str) -> str:
    basename = os.path.splitext(os.path.basename(input_path))[0]
    return os.path.join(output_dir, f"{basename}_out.mp4")


def _expected_realbasicvsr_output_path(output_dir: str) -> str:
    return os.path.join(output_dir, "output.mp4")


def _discover_output_path(
    backend: UpscalerBackend,
    input_path: str,
    output_path: str,
    output_dir: str,
    existing_files: set[str],
) -> str | None:
    if backend.name == "realbasicvsr":
        candidate = _expected_realbasicvsr_output_path(output_dir)
        if os.path.exists(candidate):
            return candidate

    if backend.name == "realesrgan-animevideov3":
        candidate = _expected_realesrgan_output_path(input_path, output_dir)
        if os.path.exists(candidate):
            return candidate

    candidates = {
        os.path.join(output_dir, name)
        for name in os.listdir(output_dir)
        if os.path.isfile(os.path.join(output_dir, name))
    }
    new_files = sorted(
        candidates - existing_files,
        key=os.path.getmtime,
        reverse=True,
    )
    if new_files:
        return new_files[0]

    video_files = [
        path
        for path in candidates
        if path.lower().endswith((".mp4", ".mov", ".mkv", ".avi"))
    ]
    if len(video_files) == 1:
        return video_files[0]

    return None


class UpscaleCancelledError(RuntimeError):
    """Raised when a running upscale subprocess is cancelled by the worker."""


def upscale_video(
    input_path: str,
    output_path: str,
    model: str = "realesrgan-animevideov3",
    scale: int = 2,
    target_width: int | None = None,
    target_height: int | None = None,
    engine_dir: str = "/engines/upscale",
    weights_dir: str = "/models",
    timeout_seconds: int = 1800,
    cancellation: RuntimeCancellationProbe | None = None,
) -> dict[str, Any]:
    """Run a video upscaler backend as a subprocess.

    Args:
        input_path: Path to the input video file.
        output_path: Expected path for the output video file.
        model: Backend name key in UPSCALE_BACKENDS.
        scale: Upscaling factor.
        target_width: Target output width (used by SeedVR2).
        target_height: Target output height (used by SeedVR2).
        engine_dir: Root directory containing backend-specific inference scripts.
        weights_dir: Root directory containing backend-specific model weight files.
        timeout_seconds: Maximum seconds to wait before killing the process.
        cancellation: Optional ``RuntimeCancellationProbe`` used by the worker
            to abort a running job at safe checkpoint boundaries.

    Returns:
        Dict with output_path, model, and scale.

    Raises:
        ValueError: If the model name is not in the registry.
        RuntimeError: If the subprocess returns a non-zero exit code.
        TimeoutError: If the subprocess exceeds the timeout.
        FileNotFoundError: If the output file is not created.
    """
    backend = UPSCALE_BACKENDS.get(model)
    if backend is None:
        raise ValueError(
            f"Unknown upscale model '{model}'. "
            f"Available: {', '.join(UPSCALE_BACKENDS.keys())}"
        )

    validation_error = backend.validate_params(
        scale=scale,
        target_width=target_width,
        target_height=target_height,
    )
    if validation_error is not None:
        raise ValueError(validation_error)

    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    pre_existing_files = _list_files(output_dir)
    cmd = backend.build_command(
        input_path=input_path,
        output_dir=output_dir,
        engine_dir=engine_dir,
        weights_dir=weights_dir,
        scale=scale,
        target_width=target_width,
        target_height=target_height,
    )

    print(f"Upscaling: {' '.join(cmd)}", flush=True)

    try:
        result = run_cancellable_process(
            cmd,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
            text=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Upscaling timed out after {timeout_seconds} seconds")
    except ProcessCancelledError as exc:
        raise UpscaleCancelledError(
            "Upscaling cancelled by user\n"
            f"STDOUT:{output_tail(exc.stdout)}\n"
            f"STDERR:{output_tail(exc.stderr)}"
        ) from exc

    proc = result.process
    stdout = result.stdout
    stderr = result.stderr

    if proc.returncode != 0:
        raise RuntimeError(f"Upscaling failed: {output_tail(stderr)}")

    if not os.path.exists(output_path):
        candidate = _discover_output_path(
            backend,
            input_path=input_path,
            output_path=output_path,
            output_dir=output_dir,
            existing_files=pre_existing_files,
        )
        if candidate is None:
            raise FileNotFoundError(f"Output file not created at {output_path}")
        os.replace(candidate, output_path)

    return {
        "output_path": output_path,
        "model": model,
        "scale": scale,
    }
