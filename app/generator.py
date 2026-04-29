import os
import subprocess
import uuid
from typing import Optional

from .process_runner import (
    ProcessCancelledError,
    output_tail,
    run_cancellable_process,
)

from .settings import settings


def log_startup_diagnostics() -> None:
    print("All imports successful", flush=True)

    if os.path.exists(settings.panowan_engine_dir):
        print(f"PanoWan dir: OK ({settings.panowan_engine_dir})", flush=True)
        models_dir = os.path.join(settings.panowan_engine_dir, "models")
        if os.path.exists(models_dir):
            print(f"Models dir contents: {os.listdir(models_dir)}", flush=True)
    else:
        print(
            f"WARNING: PanoWan dir not found at {settings.panowan_engine_dir}",
            flush=True,
        )

    uv_check = subprocess.run(["which", "uv"], capture_output=True, text=True)
    print(f"uv location: {uv_check.stdout.strip() or 'NOT FOUND'}", flush=True)


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


def _payload_int(payload: dict, key: str) -> Optional[int]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def resolve_inference_params(payload: dict) -> dict:
    """Resolve inference parameters from payload, applying quality preset if specified."""
    stored_params = (
        payload.get("params") if isinstance(payload.get("params"), dict) else {}
    )
    preset_name = payload.get("quality")
    preset = _QUALITY_PRESETS.get(preset_name, {})

    return {
        "num_inference_steps": _payload_int(stored_params, "num_inference_steps")
        or _payload_int(payload, "num_inference_steps")
        or preset.get("num_inference_steps")
        or settings.default_num_inference_steps,
        "width": _payload_int(stored_params, "width")
        or _payload_int(payload, "width")
        or preset.get("width")
        or settings.default_width,
        "height": _payload_int(stored_params, "height")
        or _payload_int(payload, "height")
        or preset.get("height")
        or settings.default_height,
        "seed": _payload_int(stored_params, "seed")
        or _payload_int(payload, "seed")
        or 0,
        "negative_prompt": stored_params.get("negative_prompt")
        or payload.get("negative_prompt")
        or "",
    }


def generate_video(payload: dict) -> dict:
    # job_id key is the canonical identifier set by the worker/job store;
    # fall back to id for direct API callers, then generate a UUID as last resort.
    job_id = str(payload.get("job_id") or payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    params = resolve_inference_params(payload)
    should_cancel = payload.get("_should_cancel")

    print(f"=== Job received: {job_id} ===", flush=True)
    print(f"Prompt: {prompt[:100]}", flush=True)
    print(
        f"Params: steps={params['num_inference_steps']} "
        f"{params['width']}x{params['height']} seed={params['seed']}",
        flush=True,
    )

    os.makedirs(settings.output_dir, exist_ok=True)
    output_path = os.path.join(settings.output_dir, f"output_{job_id}.mp4")
    cmd = [
        "uv",
        "run",
        "panowan-test",
        "--wan-model-path",
        settings.wan_model_path,
        "--lora-checkpoint-path",
        settings.lora_checkpoint_path,
        "--output-path",
        output_path,
        "--prompt",
        prompt,
        "--num-inference-steps",
        str(params["num_inference_steps"]),
        "--width",
        str(params["width"]),
        "--height",
        str(params["height"]),
        "--seed",
        str(params["seed"]),
    ]
    if params["negative_prompt"]:
        cmd += ["--negative-prompt", params["negative_prompt"]]

    print(f"Running: {' '.join(cmd)}", flush=True)

    try:
        result = run_cancellable_process(
            cmd,
            cwd=settings.panowan_engine_dir,
            timeout_seconds=settings.generation_timeout_seconds,
            should_cancel=should_cancel if callable(should_cancel) else None,
            text=True,
        )
    except subprocess.TimeoutExpired:
        print("ERROR: Generation timed out", flush=True)
        raise TimeoutError(
            "Generation timed out after "
            f"{settings.generation_timeout_seconds} seconds"
        )
    except ProcessCancelledError as exc:
        print("ERROR: Generation cancelled", flush=True)
        raise JobCancelledError(
            "Generation cancelled by user\n"
            f"STDOUT:{output_tail(exc.stdout)}\n"
            f"STDERR:{output_tail(exc.stderr)}"
        ) from exc

    process = result.process
    stdout = result.stdout
    stderr = result.stderr

    print(f"Return code: {process.returncode}", flush=True)
    if stdout:
        print(f"Stdout: {output_tail(stdout)}", flush=True)
    if stderr:
        print(f"Stderr: {output_tail(stderr)}", flush=True)

    if process.returncode != 0:
        raise RuntimeError(f"Generation failed: {output_tail(stderr)}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Output file not created")

    video_size = os.path.getsize(output_path)
    print(f"=== Job complete, video size: {video_size} bytes ===", flush=True)

    return {
        "id": job_id,
        "prompt": prompt,
        "format": "mp4",
        "output_path": output_path,
    }
