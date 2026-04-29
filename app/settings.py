import os
from dataclasses import dataclass

from .paths import (
    default_runtime_roots,
    job_store_path,
    lora_checkpoint_path,
    model_root_path,
    output_dir_path,
    repo_root_from,
    wan_diffusion_path,
    wan_t5_path,
    worker_store_path,
)


def _in_container() -> bool:
    """Best-effort detection of whether we're running inside a Docker container."""
    if os.path.isfile("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
            return "docker" in handle.read()
    except OSError:
        pass
    return bool(os.getenv("SERVICE_ROLE"))


_HOST_ROOT = repo_root_from(__file__)


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
        return wan_diffusion_path(self.wan_model_absolute_path)

    @property
    def wan_t5_absolute_path(self) -> str:
        return wan_t5_path(self.wan_model_absolute_path)

    @property
    def lora_absolute_path(self) -> str:
        return self.lora_checkpoint_path


def load_settings() -> Settings:
    roots = default_runtime_roots(repo_root=_HOST_ROOT, in_container=_in_container())
    model_root = os.getenv("MODEL_ROOT", roots.model_root)
    # Runtime storage needs a root-level override for tests and alternate mounts,
    # but leaf paths stay derived so jobs/workers/outputs cannot drift apart.
    runtime_dir = os.getenv("RUNTIME_DIR", roots.runtime_root)
    output_dir = output_dir_path(runtime_dir)

    return Settings(
        service_title="PanoWan Product Runtime API",
        service_version="1.0.0",
        panowan_engine_dir=roots.panowan_engine_root,
        model_root=model_root,
        wan_model_path=model_root_path(model_root),
        lora_checkpoint_path=lora_checkpoint_path(model_root),
        runtime_dir=runtime_dir,
        output_dir=output_dir,
        job_store_path=job_store_path(runtime_dir),
        worker_store_path=worker_store_path(runtime_dir),
        default_prompt=os.getenv(
            "DEFAULT_PROMPT", "A beautiful mountain landscape at sunset"
        ),
        generation_timeout_seconds=int(os.getenv("GENERATION_TIMEOUT_SECONDS", "1800")),
        default_num_inference_steps=int(os.getenv("DEFAULT_NUM_INFERENCE_STEPS", "50")),
        default_width=int(os.getenv("DEFAULT_WIDTH", "896")),
        default_height=int(os.getenv("DEFAULT_HEIGHT", "448")),
        upscale_engine_dir=roots.upscale_engine_root,
        # ADR 0003: weights live under model-family folders directly under
        # MODEL_ROOT (e.g. /models/Real-ESRGAN/...), not under a functional
        # /models/upscale/ grouping. Default = MODEL_ROOT.
        upscale_weights_dir=model_root,
        upscale_output_dir=output_dir,
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
