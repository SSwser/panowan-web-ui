import json
import os
import uuid

from .process_runner import ProcessCancelledError, output_tail, run_cancellable_process
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


class JobCancelledError(RuntimeError):
    pass


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
    preset_name = payload.get("quality")
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
            _payload_int(stored_params, "seed")
            or _payload_int(payload, "seed")
            or 0
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
    negative_prompt = _require_field(payload, "negative_prompt")
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


def generate_video(payload: dict) -> dict:
    job_id = str(payload.get("id") or payload.get("job_id") or uuid.uuid4())
    should_cancel = payload.get("_should_cancel")
    runner_payload = build_runner_payload({**payload, "id": job_id})
    output_path = runner_payload["output_path"]

    scratch_dir = os.path.join(settings.panowan_runner_job_dir)
    result_path = os.path.join(scratch_dir, f"{job_id}.result.json")
    job_path = os.path.join(scratch_dir, f"{job_id}.json")
    runner_payload["result_path"] = result_path

    os.makedirs(scratch_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(job_path, "w", encoding="utf-8") as handle:
        json.dump(runner_payload, handle, ensure_ascii=False)

    cmd = ["python", "runner.py", "--job", job_path]

    try:
        result = run_cancellable_process(
            cmd,
            cwd=settings.panowan_engine_dir,
            timeout_seconds=settings.generation_timeout_seconds,
            should_cancel=should_cancel if callable(should_cancel) else None,
            text=True,
        )
    except __import__("subprocess").TimeoutExpired:
        raise TimeoutError(
            f"Generation timed out after {settings.generation_timeout_seconds} seconds"
        )
    except ProcessCancelledError as exc:
        raise JobCancelledError(
            "Generation cancelled\n"
            f"STDOUT:{output_tail(exc.stdout)}\n"
            f"STDERR:{output_tail(exc.stderr)}"
        ) from exc

    process = result.process
    if process.returncode != 0:
        raise RuntimeError(f"Generation failed: {output_tail(result.stderr)}")
    if not os.path.exists(output_path):
        raise FileNotFoundError("Output file not created")

    return {
        "id": job_id,
        "prompt": runner_payload["prompt"],
        "format": "mp4",
        "output_path": output_path,
    }
