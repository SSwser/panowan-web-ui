import os
import subprocess
import uuid
from typing import Optional

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


def _payload_int(payload: dict, key: str) -> Optional[int]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def resolve_inference_params(payload: dict) -> dict:
    """Resolve inference parameters from payload, applying quality preset if specified."""
    preset_name = payload.get("quality")
    preset = _QUALITY_PRESETS.get(preset_name, {})

    return {
        "num_inference_steps": _payload_int(payload, "num_inference_steps")
        or preset.get("num_inference_steps")
        or settings.default_num_inference_steps,
        "width": _payload_int(payload, "width")
        or preset.get("width")
        or settings.default_width,
        "height": _payload_int(payload, "height")
        or preset.get("height")
        or settings.default_height,
        "seed": _payload_int(payload, "seed") or 0,
        "negative_prompt": payload.get("negative_prompt") or "",
    }


def generate_video(payload: dict) -> dict:
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)
    params = resolve_inference_params(payload)

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
        process = subprocess.Popen(
            cmd,
            cwd=settings.panowan_engine_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(
            timeout=settings.generation_timeout_seconds
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        print("ERROR: Generation timed out", flush=True)
        raise TimeoutError(
            "Generation timed out after "
            f"{settings.generation_timeout_seconds} seconds"
        )

    print(f"Return code: {process.returncode}", flush=True)
    if stdout:
        print(f"Stdout: {stdout[-500:]}", flush=True)
    if stderr:
        print(f"Stderr: {stderr[-500:]}", flush=True)

    if process.returncode != 0:
        raise RuntimeError(f"Generation failed: {stderr[-500:]}")

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
