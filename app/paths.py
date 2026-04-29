import os
import posixpath
from dataclasses import dataclass


CONTAINER_MODEL_ROOT = "/models"
CONTAINER_RUNTIME_ROOT = "/app/runtime"
CONTAINER_PANOWAN_ENGINE_ROOT = "/engines/panowan"
CONTAINER_UPSCALE_ENGINE_ROOT = "/engines/upscale"

WAN_MODEL_RELATIVE_PATH = "Wan-AI/Wan2.1-T2V-1.3B"
LORA_CHECKPOINT_RELATIVE_PATH = "PanoWan/latest-lora.ckpt"
UPSCALE_RELATIVE_PATH = "Upscale"
OUTPUTS_DIRNAME = "outputs"
JOBS_FILENAME = "jobs.json"
WORKERS_FILENAME = "workers.json"
WAN_DIFFUSION_FILENAME = "diffusion_pytorch_model.safetensors"
WAN_T5_FILENAME = "models_t5_umt5-xxl-enc-bf16.pth"


@dataclass(frozen=True)
class RuntimePathRoots:
    repo_root: str
    model_root: str
    runtime_root: str
    panowan_engine_root: str
    upscale_engine_root: str


def container_join(base: str, *parts: str) -> str:
    # Use POSIX joining only for absolute POSIX (container) paths.
    # On a Windows host the base is a native path, so os.path.join is correct.
    if base.startswith("/"):
        cleaned_parts = [part.strip("/") for part in parts if part]
        if not cleaned_parts:
            return base
        base_clean = base.rstrip("/") or "/"
        return posixpath.join(base_clean, *cleaned_parts)
    return os.path.join(base, *parts)


def container_child(path: str, child: str) -> str:
    return container_join(path, child)


def repo_root_from(file_path: str) -> str:
    return os.path.dirname(os.path.abspath(file_path)).rsplit(os.sep + "app", 1)[0]


def default_runtime_roots(*, repo_root: str, in_container: bool) -> RuntimePathRoots:
    data_root = os.path.join(repo_root, "data")
    third_party_root = os.path.join(repo_root, "third_party")
    return RuntimePathRoots(
        repo_root=repo_root,
        model_root=(
            CONTAINER_MODEL_ROOT if in_container else os.path.join(data_root, "models")
        ),
        runtime_root=(
            CONTAINER_RUNTIME_ROOT
            if in_container
            else os.path.join(data_root, "runtime")
        ),
        panowan_engine_root=(
            CONTAINER_PANOWAN_ENGINE_ROOT
            if in_container
            else os.path.join(third_party_root, "PanoWan")
        ),
        upscale_engine_root=(
            CONTAINER_UPSCALE_ENGINE_ROOT
            if in_container
            else os.path.join(third_party_root, UPSCALE_RELATIVE_PATH)
        ),
    )


def model_root_path(model_root: str) -> str:
    return container_join(model_root, WAN_MODEL_RELATIVE_PATH)


def lora_checkpoint_path(model_root: str) -> str:
    return container_join(model_root, LORA_CHECKPOINT_RELATIVE_PATH)


def output_dir_path(runtime_root: str) -> str:
    return container_child(runtime_root, OUTPUTS_DIRNAME)


def job_store_path(runtime_root: str) -> str:
    return container_child(runtime_root, JOBS_FILENAME)


def worker_store_path(runtime_root: str) -> str:
    return container_child(runtime_root, WORKERS_FILENAME)


def wan_diffusion_path(wan_model_path: str) -> str:
    return container_child(wan_model_path, WAN_DIFFUSION_FILENAME)


def wan_t5_path(wan_model_path: str) -> str:
    return container_child(wan_model_path, WAN_T5_FILENAME)
