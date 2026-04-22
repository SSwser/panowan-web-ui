import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_title: str
    service_version: str
    panowan_dir: str
    wan_model_path: str
    lora_checkpoint_path: str
    runtime_dir: str
    output_dir: str
    job_store_path: str
    default_prompt: str
    generation_timeout_seconds: int
    host: str
    port: int

    @property
    def wan_model_absolute_path(self) -> str:
        return os.path.join(self.panowan_dir, self.wan_model_path.lstrip("./"))

    @property
    def wan_diffusion_absolute_path(self) -> str:
        return os.path.join(
            self.wan_model_absolute_path, "diffusion_pytorch_model.safetensors"
        )

    @property
    def wan_t5_absolute_path(self) -> str:
        return os.path.join(
            self.wan_model_absolute_path,
            "models_t5_umt5-xxl-enc-bf16.pth",
        )

    @property
    def lora_absolute_path(self) -> str:
        return os.path.join(self.panowan_dir, self.lora_checkpoint_path.lstrip("./"))


def load_settings() -> Settings:
    runtime_dir = os.getenv("RUNTIME_DIR", "/app/runtime")
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
        runtime_dir=runtime_dir,
        output_dir=os.getenv("OUTPUT_DIR", os.path.join(runtime_dir, "outputs")),
        job_store_path=os.getenv(
            "JOB_STORE_PATH", os.path.join(runtime_dir, "jobs.json")
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
