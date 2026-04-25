# NOTE: Plan specified target_dir="/engines/upscale", but that path only exists
# inside the worker container, not on the host where pytest runs. We use
# tmp_path to isolate verify behavior while preserving the plan's intent:
# "spec for submodule with present file ⇒ empty missing list".
from pathlib import Path

from app.backends.model_manager import ModelManager
from app.backends.model_spec import FileCheck, ModelSpec
from app.backends.model_specs import load_model_specs
from app.settings import settings


def test_model_manager_uses_registered_provider_for_submodule_specs(
    tmp_path: Path,
) -> None:
    target = tmp_path / "engines" / "upscale"
    (target / "realesrgan").mkdir(parents=True)
    (target / "realesrgan" / "inference_realesrgan_video.py").write_text(
        "", encoding="utf-8"
    )
    spec = ModelSpec(
        name="upscale-engine",
        source_type="submodule",
        source_ref="",
        target_dir=str(target),
        files=[FileCheck(path="realesrgan/inference_realesrgan_video.py")],
    )
    manager = ModelManager()
    result = manager.verify([spec])
    assert result == []


def test_load_model_specs_includes_upscale_backend_items() -> None:
    specs = load_model_specs(settings)
    names = {spec.name for spec in specs}
    assert "panowan-engine" in names
    assert "upscale-realesrgan-engine" in names
