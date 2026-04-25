"""Shared runtime contract constants for vendored upscale backends.

These values are the single source of truth for the RealESRGAN backend's
runtime contract (engine files, weight files, required commands, backend
runtime interpreter, required Python modules). They are consumed by both
``app.upscaler`` (for availability checks and command construction) and
``app.backends.model_specs`` (for model provisioning), so any path change here
must keep both in sync automatically.

File-path conventions:
    * ``REALESRGAN_ENGINE_FILES`` paths are relative to ``UPSCALE_ENGINE_DIR``
      (``/engines/upscale`` in containers). The flat layout under
      ``realesrgan/vendor/`` is the long-lived contract — see
      ``docs/superpowers/specs/2026-04-25-upscale-backend-integration-design.md``.
    * ``REALESRGAN_WEIGHT_FILES`` paths are relative to ``UPSCALE_WEIGHTS_DIR``
      (``MODEL_ROOT`` / ``/models`` in containers). Weights live under the
      model-family folder ``Real-ESRGAN/`` directly under ``MODEL_ROOT``,
      not under any functional ``upscale/`` grouping (ADR 0003).
"""

# Flat vendored runtime: ``vendor/__main__.py`` is the deterministic
# entrypoint that prepends ``vendor/`` to ``sys.path`` and delegates to
# ``inference_realesrgan_video.main()``.
REALESRGAN_ENGINE_FILES: tuple[str, ...] = (
    "vendor/__main__.py",
    "vendor/inference_realesrgan_video.py",
    "vendor/realesrgan/__init__.py",
    "vendor/realesrgan/utils.py",
    "vendor/realesrgan/archs/__init__.py",
    "vendor/realesrgan/archs/srvgg_arch.py",
)

# Weight folder name under MODEL_ROOT. Kept as a constant so upscaler command
# construction and ModelSpec target_dir derivation stay in lockstep.
REALESRGAN_WEIGHT_FAMILY: str = "Real-ESRGAN"
REALESRGAN_WEIGHT_FILENAME: str = "realesr-animevideov3.pth"

REALESRGAN_WEIGHT_FILES: tuple[str, ...] = (
    f"{REALESRGAN_WEIGHT_FAMILY}/{REALESRGAN_WEIGHT_FILENAME}",
)

REALESRGAN_REQUIRED_COMMANDS: tuple[str, ...] = ("ffmpeg",)

REALESRGAN_RUNTIME_PYTHON = "/opt/venvs/upscale-realesrgan/bin/python"

# Modules installed into the backend venv itself. The vendored ``realesrgan``
# package is validated via ``REALESRGAN_ENGINE_FILES`` above.
REALESRGAN_RUNTIME_MODULES: tuple[str, ...] = ("cv2", "ffmpeg", "tqdm")
