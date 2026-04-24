import os

from app.generator import generate_video
from app.settings import settings
from app.upscaler import upscale_video

from .base import EngineResult


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v", "upscale")

    def validate_runtime(self) -> None:
        missing = []
        for path in (
            settings.panowan_engine_dir,
            settings.wan_diffusion_absolute_path,
            settings.wan_t5_absolute_path,
            settings.lora_absolute_path,
        ):
            if not os.path.exists(path):
                missing.append(path)
        if missing:
            joined = "\n".join(f"- {path}" for path in missing)
            raise FileNotFoundError(
                "PanoWan runtime assets are missing. Run `make setup-models` first:\n"
                f"{joined}"
            )

    def run(self, job: dict) -> EngineResult:
        job_type = job.get("type", "generate")
        if job_type == "upscale":
            params = job.get("upscale_params") or {}
            result = upscale_video(
                input_path=job["source_output_path"],
                output_path=job["output_path"],
                model=params["model"],
                scale=params["scale"],
                target_width=params.get("target_width"),
                target_height=params.get("target_height"),
                model_dir=settings.upscale_model_dir,
                timeout_seconds=settings.upscale_timeout_seconds,
            )
            return EngineResult(output_path=result["output_path"], metadata={})

        result = generate_video(job)
        return EngineResult(output_path=result["output_path"], metadata={})
