import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_title: str
    service_version: str
    panowan_dir: str
    wan_model_path: str
    lora_checkpoint_path: str
    default_prompt: str
    generation_timeout_seconds: int
    host: str
    port: int

    @property
    def wan_model_absolute_path(self) -> str:
        return os.path.join(self.panowan_dir, self.wan_model_path.lstrip("./"))

    @property
    def lora_absolute_path(self) -> str:
        return os.path.join(self.panowan_dir, self.lora_checkpoint_path.lstrip("./"))


def load_settings() -> Settings:
    return Settings(
        service_title="PanoWan Local Service",
        service_version="1.0.0",
        panowan_dir=os.getenv("PANOWAN_DIR", "/app/PanoWan"),
        wan_model_path=os.getenv(
            "WAN_MODEL_PATH", "./models/Wan-AI/Wan2.1-T2V-1.3B"
        ),
        lora_checkpoint_path=os.getenv(
            "LORA_CHECKPOINT_PATH", "./models/PanoWan/latest-lora.ckpt"
        ),
        default_prompt=os.getenv(
            "DEFAULT_PROMPT", "A beautiful mountain landscape at sunset"
        ),
        generation_timeout_seconds=int(
            os.getenv("GENERATION_TIMEOUT_SECONDS", "1800")
        ),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )


settings = load_settings()
