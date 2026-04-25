import os

from app.settings import settings
from app.upscaler import upscale_video

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
                "Upscale runtime assets are missing. Run `make setup-models` first:\n"
                f"{joined}"
            )

    def run(self, job: dict) -> EngineResult:
        params = job.get("upscale_params") or {}
        should_cancel = job.get("_should_cancel")
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
            should_cancel=should_cancel if callable(should_cancel) else None,
        )
        return EngineResult(output_path=result["output_path"], metadata={})
