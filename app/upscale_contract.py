"""Shared runtime contract constants for vendored upscale backends."""

REALESRGAN_ENGINE_FILES: tuple[str, ...] = (
    "realesrgan/adapter.py",
    "realesrgan/vendor/Real-ESRGAN/inference_realesrgan_video.py",
    "realesrgan/vendor/Real-ESRGAN/realesrgan/__init__.py",
    "realesrgan/vendor/Real-ESRGAN/realesrgan/utils.py",
    "realesrgan/vendor/Real-ESRGAN/realesrgan/archs/__init__.py",
    "realesrgan/vendor/Real-ESRGAN/realesrgan/archs/srvgg_arch.py",
)

REALESRGAN_WEIGHT_FILES: tuple[str, ...] = ("realesrgan/realesr-animevideov3.pth",)

REALESRGAN_REQUIRED_COMMANDS: tuple[str, ...] = ("ffmpeg",)

REALESRGAN_RUNTIME_PYTHON = "/opt/venvs/upscale-realesrgan/bin/python"

# These are the modules installed into the backend venv itself. The vendored
# `realesrgan` package is validated via the required engine files above.
REALESRGAN_RUNTIME_MODULES: tuple[str, ...] = ("cv2", "ffmpeg", "tqdm")
