import os

from app.generator import generate_video
from app.settings import settings

from .base import EngineResult


class PanoWanEngine:
    name = "panowan"
    capabilities = ("t2v", "i2v")

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
                "PanoWan runtime assets are missing. Run `make setup-backends` first:\n"
                f"{joined}"
            )

    def run(self, job: dict) -> EngineResult:
        result = generate_video(job)
        return EngineResult(output_path=result["output_path"], metadata={})
