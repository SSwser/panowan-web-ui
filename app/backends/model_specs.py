import os
from pathlib import Path

from app.paths import container_child
from app.settings import Settings

from .model_spec import FileCheck, ModelSpec
from .registry import discover


def _load_realesrgan_backend_spec(backend_root: Path):
    spec = next(
        (spec for spec in discover(backend_root) if spec.backend.name == "realesrgan"),
        None,
    )
    if spec is None:
        raise RuntimeError(f"Backend spec realesrgan not found in {backend_root}")
    return spec


def load_model_specs(settings: Settings) -> list[ModelSpec]:
    realesrgan = _load_realesrgan_backend_spec(Path(settings.upscale_engine_dir))
    if realesrgan.weights.family is None:
        raise RuntimeError("Backend spec realesrgan missing weights.family")
    if realesrgan.weights.filename is None:
        raise RuntimeError("Backend spec realesrgan missing weights.filename")

    return [
        ModelSpec(
            name="wan-t2v-1.3b",
            source_type="huggingface",
            source_ref="Wan-AI/Wan2.1-T2V-1.3B",
            target_dir=settings.wan_model_path,
            files=[
                FileCheck(path="diffusion_pytorch_model.safetensors"),
                FileCheck(path="models_t5_umt5-xxl-enc-bf16.pth"),
            ],
        ),
        ModelSpec(
            name="panowan-lora",
            source_type="huggingface",
            source_ref="YOUSIKI/PanoWan",
            target_dir=os.path.dirname(settings.lora_checkpoint_path),
            files=[
                FileCheck(path=os.path.basename(settings.lora_checkpoint_path)),
            ],
        ),
        ModelSpec(
            name="panowan-engine",
            source_type="submodule",
            source_ref="",
            target_dir=settings.panowan_engine_dir,
            files=[FileCheck(path="pyproject.toml")],
        ),
        ModelSpec(
            name="upscale-realesrgan-weights",
            source_type="http",
            source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
            target_dir=container_child(
                settings.upscale_weights_dir, realesrgan.weights.family
            ),
            files=[
                FileCheck(
                    path=realesrgan.weights.filename,
                    sha256="b8a8376811077954d82ca3fcf476f1ac3da3e8a68a4f4d71363008000a18b75d",
                )
            ],
        ),
    ]
