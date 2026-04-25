import os

from app.paths import container_child
from app.settings import Settings
from app.upscale_contract import REALESRGAN_ENGINE_FILES

from .registry import FileCheck, ModelSpec


def load_specs(settings: Settings) -> list[ModelSpec]:
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
            name="upscale-realesrgan-engine",
            source_type="submodule",
            source_ref="",
            target_dir=settings.upscale_engine_dir,
            files=[FileCheck(path=path) for path in REALESRGAN_ENGINE_FILES],
        ),
        ModelSpec(
            name="upscale-realesrgan-weights",
            source_type="http",
            source_ref="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
            target_dir=container_child(settings.upscale_weights_dir, "realesrgan"),
            files=[
                FileCheck(
                    path="realesr-animevideov3.pth",
                    sha256="b8a8376811077954d82ca3fcf476f1ac3da3e8a68a4f4d71363008000a18b75d",
                )
            ],
        ),
    ]
