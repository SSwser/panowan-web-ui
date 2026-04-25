import os
from pathlib import PurePath
from dataclasses import dataclass

from .paths import container_child, container_join


def _in_container() -> bool:
    """Best-effort detection of whether we're running inside a Docker container."""
    if os.path.isfile("/.dockerenv"):
        return True
    try:
        return "docker" in os.readline("/proc/1/cgroup")
    except (OSError, AttributeError):
        pass
    return bool(os.getenv("SERVICE_ROLE"))


# Host-side project roots (submodule checkouts live under these).
_HOST_ROOT = os.path.dirname(os.path.abspath(__file__)).rsplit(os.sep + "app", 1)[0]
_HOST_THIRD_PARTY = os.path.join(_HOST_ROOT, "third_party")


@dataclass(frozen=True)
class Settings:
    service_title: str
    service_version: str
    panowan_engine_dir: str
    model_root: str
    wan_model_path: str
    lora_checkpoint_path: str
    runtime_dir: str
    output_dir: str
    job_store_path: str
    worker_store_path: str
    default_prompt: str
    generation_timeout_seconds: int
    default_num_inference_steps: int
    default_width: int
    default_height: int
    upscale_engine_dir: str
    upscale_weights_dir: str
    upscale_output_dir: str
    upscale_timeout_seconds: int
    max_concurrent_jobs: int
    host: str
    port: int
    worker_poll_interval_seconds: float
    worker_stale_seconds: float

    @property
    def wan_model_absolute_path(self) -> str:
        return self.wan_model_path

    @property
    def wan_diffusion_absolute_path(self) -> str:
        return container_child(
            self.wan_model_absolute_path, "diffusion_pytorch_model.safetensors"
        )

    @property
    def wan_t5_absolute_path(self) -> str:
        return container_child(
            self.wan_model_absolute_path, "models_t5_umt5-xxl-enc-bf16.pth"
        )

    @property
    def lora_absolute_path(self) -> str:
        return self.lora_checkpoint_path


def load_settings() -> Settings:
    in_container = _in_container()

    # Host-side: ./data/models  | Container: /models (docker-compose bind-mount)
    model_root = os.getenv("MODEL_ROOT", "/models" if in_container else os.path.join(_HOST_ROOT, "data", "models"))
    runtime_dir = os.getenv("RUNTIME_DIR", "/app/runtime" if in_container else os.path.join(_HOST_ROOT, "data", "runtime"))
    output_dir = os.getenv("OUTPUT_DIR", container_child(runtime_dir, "outputs"))

    # Engine dirs: host-side points to submodule checkouts; container points to bind-mount roots.
    # PanoWan: host=third_party/PanoWan          | container=/engines/panowan
    # Upscale:  host=third_party/Upscale/realesrgan | container=/engines/upscale
    panowan_engine_dir = os.getenv(
        "PANOWAN_ENGINE_DIR",
        "/engines/panowan" if in_container else os.path.join(_HOST_THIRD_PARTY, "PanoWan")
    )
    upscale_engine_dir = os.getenv(
        "UPSCALE_ENGINE_DIR",
        "/engines/upscale" if in_container else os.path.join(_HOST_THIRD_PARTY, "Upscale", "realesrgan")
    )

    return Settings(
        service_title="PanoWan Product Runtime API",
        service_version="1.0.0",
        panowan_engine_dir=panowan_engine_dir,
        model_root=model_root,
        wan_model_path=os.getenv(
            "WAN_MODEL_PATH",
            container_join(model_root, "Wan-AI/Wan2.1-T2V-1.3B"),
        ),
        lora_checkpoint_path=os.getenv(
            "LORA_CHECKPOINT_PATH",
            container_join(model_root, "PanoWan/latest-lora.ckpt"),
        ),
        runtime_dir=runtime_dir,
        output_dir=output_dir,
        job_store_path=os.getenv(
            "JOB_STORE_PATH", container_child(runtime_dir, "jobs.json")
        ),
        worker_store_path=os.getenv(
            "WORKER_STORE_PATH", container_child(runtime_dir, "workers.json")
        ),
        default_prompt=os.getenv(
            "DEFAULT_PROMPT", "A beautiful mountain landscape at sunset"
        ),
        generation_timeout_seconds=int(os.getenv("GENERATION_TIMEOUT_SECONDS", "1800")),
        default_num_inference_steps=int(os.getenv("DEFAULT_NUM_INFERENCE_STEPS", "50")),
        default_width=int(os.getenv("DEFAULT_WIDTH", "896")),
        default_height=int(os.getenv("DEFAULT_HEIGHT", "448")),
        upscale_engine_dir=upscale_engine_dir,
        # ADR 0003: weights live under model-family folders directly under
        # MODEL_ROOT (e.g. /models/Real-ESRGAN/...), not under a functional
        # /models/upscale/ grouping. Default = MODEL_ROOT.
        upscale_weights_dir=os.getenv("UPSCALE_WEIGHTS_DIR", model_root),
        upscale_output_dir=os.getenv("UPSCALE_OUTPUT_DIR", output_dir),
        upscale_timeout_seconds=int(os.getenv("UPSCALE_TIMEOUT_SECONDS", "1800")),
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "1")),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        worker_poll_interval_seconds=float(
            os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2")
        ),
        worker_stale_seconds=float(os.getenv("WORKER_STALE_SECONDS", "60")),
    )


settings = load_settings()
