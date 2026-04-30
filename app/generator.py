import os
import uuid

from .settings import settings


def extract_prompt(payload: dict) -> str:
    if "prompt" in payload and payload["prompt"]:
        return payload["prompt"]
    nested_input = payload.get("input")
    if isinstance(nested_input, dict) and nested_input.get("prompt"):
        return nested_input["prompt"]
    return settings.default_prompt


_QUALITY_PRESETS = {
    "draft": {"num_inference_steps": 20, "width": 448, "height": 224},
    "standard": {"num_inference_steps": 50, "width": 896, "height": 448},
}


def _payload_int(payload: dict, key: str) -> int | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def _require_field(payload: dict, key: str) -> str:
    if key not in payload:
        raise ValueError(f"{key} is required")
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _resolve_task(payload: dict) -> str:
    task = payload.get("task") or payload.get("mode") or "t2v"
    if task not in {"t2v", "i2v"}:
        raise ValueError("task must be 't2v' or 'i2v'")
    return task


def resolve_inference_params(payload: dict) -> dict:
    raw_params = payload.get("params")
    stored_params = raw_params if isinstance(raw_params, dict) else {}
    # Defaulting to the draft preset keeps real-chain validation fast unless a
    # caller explicitly asks for a more expensive quality tier.
    preset_name = payload.get("quality") or "draft"
    preset = _QUALITY_PRESETS.get(preset_name, {})
    return {
        "num_inference_steps": (
            _payload_int(stored_params, "num_inference_steps")
            or _payload_int(payload, "num_inference_steps")
            or preset.get("num_inference_steps")
            or settings.default_num_inference_steps
        ),
        "width": (
            _payload_int(stored_params, "width")
            or _payload_int(payload, "width")
            or preset.get("width")
            or settings.default_width
        ),
        "height": (
            _payload_int(stored_params, "height")
            or _payload_int(payload, "height")
            or preset.get("height")
            or settings.default_height
        ),
        "seed": (
            _payload_int(stored_params, "seed") or _payload_int(payload, "seed") or 0
        ),
        "num_frames": (
            _payload_int(stored_params, "num_frames")
            or _payload_int(payload, "num_frames")
            or 81
        ),
        "guidance_scale": payload.get("guidance_scale"),
    }


def build_runner_payload(payload: dict) -> dict:
    job_id = str(payload.get("job_id") or payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    negative_prompt = payload.get("negative_prompt", "")
    params = resolve_inference_params(payload)
    task = _resolve_task(payload)
    output_path = payload.get("output_path") or os.path.join(
        settings.output_dir, f"output_{job_id}.mp4"
    )
    runner_payload: dict = {
        "version": "v1",
        "task": task,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "output_path": output_path,
        "resolution": {"width": params["width"], "height": params["height"]},
        "num_frames": params["num_frames"],
        "seed": params["seed"],
        "num_inference_steps": params["num_inference_steps"],
        "guidance_scale": params.get("guidance_scale"),
    }
    if runner_payload["guidance_scale"] is None:
        del runner_payload["guidance_scale"]
    if task == "i2v":
        runner_payload["input_image_path"] = _require_field(payload, "input_image_path")
        runner_payload["denoising_strength"] = payload["denoising_strength"]
    return runner_payload
