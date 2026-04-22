import os
import subprocess
import uuid

from .settings import settings


def log_startup_diagnostics() -> None:
    print("All imports successful", flush=True)

    if os.path.exists(settings.panowan_dir):
        print(f"PanoWan dir: OK ({settings.panowan_dir})", flush=True)
        models_dir = os.path.join(settings.panowan_dir, "models")
        if os.path.exists(models_dir):
            print(f"Models dir contents: {os.listdir(models_dir)}", flush=True)
    else:
        print(
            f"WARNING: PanoWan dir not found at {settings.panowan_dir}",
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


def generate_video(payload: dict) -> dict:
    job_id = str(payload.get("id") or uuid.uuid4())
    prompt = extract_prompt(payload)

    print(f"=== Job received: {job_id} ===", flush=True)
    print(f"Prompt: {prompt[:100]}", flush=True)

    output_path = f"/tmp/output_{job_id}.mp4"
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
    ]

    print(f"Running: {' '.join(cmd)}", flush=True)

    try:
        result = subprocess.run(
            cmd,
            cwd=settings.panowan_dir,
            capture_output=True,
            text=True,
            timeout=settings.generation_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        print("ERROR: Generation timed out", flush=True)
        raise TimeoutError(
            "Generation timed out after "
            f"{settings.generation_timeout_seconds} seconds"
        ) from exc

    print(f"Return code: {result.returncode}", flush=True)
    if result.stdout:
        print(f"Stdout: {result.stdout[-500:]}", flush=True)
    if result.stderr:
        print(f"Stderr: {result.stderr[-500:]}", flush=True)

    if result.returncode != 0:
        raise RuntimeError(f"Generation failed: {result.stderr[-500:]}")

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
