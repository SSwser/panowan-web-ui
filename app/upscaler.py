"""Upscaler module: Protocol-based backend registry for video upscaling."""

import os
import subprocess
import sys
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class UpscalerBackend(Protocol):
    """Protocol defining the interface for an upscaler backend."""

    name: str
    display_name: str
    default_scale: int
    max_scale: int

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        model_dir: str,
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

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        model_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        script = os.path.join(model_dir, "realesrgan", "inference_realesrgan_video.py")
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

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        model_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        script = os.path.join(model_dir, "realbasicvsr", "inference_realbasicvsr.py")
        config = os.path.join(
            model_dir, "realbasicvsr", "configs", "realbasicvsr_x4.py"
        )
        checkpoint = os.path.join(
            model_dir, "realbasicvsr", "experiments", "RealBasicVSR_x4.pth"
        )
        output_path = os.path.join(output_dir, "output.mp4")
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
                f"{self.display_name} only supports 4x upscaling, "
                f"got scale={scale}"
            )
        return None


class SeedVR2Backend:
    """SeedVR2-3B upscaler backend (state-of-the-art)."""

    name: str = "seedvr2-3b"
    display_name: str = "SeedVR2-3B (SOTA)"
    default_scale: int = 2
    max_scale: int = 4

    def build_command(
        self,
        input_path: str,
        output_dir: str,
        model_dir: str,
        scale: int,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> list[str]:
        script = os.path.join(
            model_dir, "seedvr2", "projects", "inference_seedvr2_3b.py"
        )
        input_dir = os.path.dirname(input_path)
        res_w = str(target_width) if target_width else "896"
        res_h = str(target_height) if target_height else "448"
        return [
            "torchrun",
            f"--nproc_per_node=1",
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


def upscale_video(
    input_path: str,
    output_path: str,
    model: str = "realesrgan-animevideov3",
    scale: int = 2,
    target_width: int | None = None,
    target_height: int | None = None,
    model_dir: str = "/app/data/models/upscale",
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Run a video upscaler backend as a subprocess.

    Args:
        input_path: Path to the input video file.
        output_path: Expected path for the output video file.
        model: Backend name key in UPSCALE_BACKENDS.
        scale: Upscaling factor.
        target_width: Target output width (used by SeedVR2).
        target_height: Target output height (used by SeedVR2).
        model_dir: Root directory containing model scripts and weights.
        timeout_seconds: Maximum seconds to wait before killing the process.

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
        model_dir=model_dir,
        scale=scale,
        target_width=target_width,
        target_height=target_height,
    )

    print(f"Upscaling: {' '.join(cmd)}", flush=True)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise TimeoutError(
            f"Upscaling timed out after {timeout_seconds} seconds"
        )

    if proc.returncode != 0:
        stderr_tail = stderr[-500:].decode(errors="replace") if stderr else ""
        raise RuntimeError(f"Upscaling failed: {stderr_tail}")

    if not os.path.exists(output_path):
        raise FileNotFoundError(
            f"Output file not created at {output_path}"
        )

    return {
        "output_path": output_path,
        "model": model,
        "scale": scale,
    }
