from app.backends.model_specs import load_model_specs
from app.settings import settings


def test_load_model_specs_keeps_model_subflow_separate_from_backend_vendor_flow() -> None:
    specs = load_model_specs(settings)
    names = {spec.name for spec in specs}
    assert "panowan-engine" in names
    assert "upscale-realesrgan-engine" not in names
    assert "upscale-realesrgan-weights" in names


def test_load_model_specs_only_keeps_submodule_source_for_panowan_engine() -> None:
    specs = load_model_specs(settings)
    submodule_names = {spec.name for spec in specs if spec.source_type == "submodule"}
    assert submodule_names == {"panowan-engine"}


def test_load_model_specs_preserves_weight_artifact_contract() -> None:
    specs = load_model_specs(settings)
    names = {spec.name for spec in specs}
    assert "wan-t2v-1.3b" in names
    assert "panowan-lora" in names
    assert "upscale-realesrgan-weights" in names
