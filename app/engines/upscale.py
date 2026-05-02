import os

from app.cancellation import RuntimeCancellationProbe
from app.settings import settings
from app.upscaler import get_available_upscale_backends, upscale_video

from .base import EngineResult


class UpscaleEngine:
    name = "upscale"
    capabilities = ("upscale",)

    def validate_runtime(self) -> None:
        missing = []
        for path in (settings.upscale_engine_dir, settings.upscale_weights_dir):
            if not os.path.exists(path):
                missing.append(path)
        if missing:
            joined = "\n".join(f"- {path}" for path in missing)
            raise FileNotFoundError(
                "Upscale runtime assets are missing. Run `make setup` first:\n"
                f"{joined}"
            )

        available = get_available_upscale_backends(
            settings.upscale_engine_dir,
            settings.upscale_weights_dir,
        )
        if not available:
            raise FileNotFoundError(
                "No available upscale backends. Run `make setup` and verify "
                f"backend assets under {settings.upscale_engine_dir} and "
                f"{settings.upscale_weights_dir}."
            )

    def run(self, job: dict) -> EngineResult:
        params = job.get("upscale_params") or {}
        cancellation = job.get("_cancellation_probe")
        if not isinstance(cancellation, RuntimeCancellationProbe):
            cancellation = None
        result = upscale_video(
            input_path=job["source_output_path"],
            output_path=job["output_path"],
            model=params["model"],
            scale=params["scale"],
            target_width=params.get("target_width"),
            target_height=params.get("target_height"),
            engine_dir=settings.upscale_engine_dir,
            weights_dir=settings.upscale_weights_dir,
            timeout_seconds=settings.upscale_timeout_seconds,
            cancellation=cancellation,
        )
        return EngineResult(output_path=result["output_path"], metadata={})
