"""Upscaler module: Protocol-based backend registry for video upscaling."""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from app.paths import container_join
from app.process_runner import (
    ProcessCancelledError,
    output_tail,
    run_cancellable_process,
)


@dataclass(frozen=True)
class UpscaleBackendAssets:
    """Files and commands a backend needs to be considered available."""

    engine_files: tuple[str, ...]
    weight_files: tuple[str, ...]
    required_commands: tuple[str, ...] = ()


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


class RealESRGANBackend:
    """Real-ESRGAN anime video upscaler backend (fast)."""

    name: str = "realesrgan-animevideov3"
    display_name: str = "Real-ESRGAN (Fast)"
    default_scale: int = 2
    max_scale: int = 4
    assets: UpscaleBackendAssets = UpscaleBackendAssets(
        engine_files=(
            "realesrgan/adapter.py",
            "realesrgan/vendor/inference_realesrgan_video.py",
        ),
        weight_files=("realesrgan/realesr-animevideov3.pth",),
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
        script = container_join(engine_dir, "realesrgan", "adapter.py")
        return [
            sys.executable,
            script,
            "-i",
            input_path,
            "-o",
            output_dir,
            "-n",
            "realesr-animevideov3",
            "-s",
            str(scale),
            "--half",
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
    weights_dir: str = "/models/upscale",
    timeout_seconds: int = 1800,
    should_cancel: Callable[[], bool] | None = None,
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
        should_cancel: Optional callback used by the worker to abort a running job.

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
            should_cancel=should_cancel,
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
        raise FileNotFoundError(f"Output file not created at {output_path}")

    return {
        "output_path": output_path,
        "model": model,
        "scale": scale,
    }
