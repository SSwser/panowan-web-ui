import os

from app.paths import container_child
from app.settings import Settings

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
            name="upscale-engine",
            source_type="submodule",
            source_ref="",
            target_dir=settings.upscale_engine_dir,
            files=[FileCheck(path="realesrgan/inference_realesrgan_video.py")],
        ),
        ModelSpec(
            name="realesrgan-weights",
            source_type="huggingface",
            source_ref="0x7a7f/realesr-animevideov3",
            target_dir=container_child(settings.upscale_weights_dir, "realesrgan"),
            files=[FileCheck(path="realesr-animevideov3.pth")],
        ),
    ]
