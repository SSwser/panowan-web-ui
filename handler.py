"""
PanoWan RunPod Serverless Handler
Generates 360 panoramic videos from text prompts using PanoWan.
"""

import sys
import traceback

print("=== PanoWan Handler Starting ===", flush=True)
print(f"Python version: {sys.version}", flush=True)

try:
    print("Importing runpod...", flush=True)
    import runpod
    print("runpod imported ok", flush=True)
except Exception as e:
    print(f"FATAL: Failed to import runpod: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

import subprocess
import os
import base64

print("All imports successful", flush=True)

# Check that key paths exist
panowan_dir = "/app/PanoWan"
if os.path.exists(panowan_dir):
    print(f"PanoWan dir: OK", flush=True)
    models_dir = os.path.join(panowan_dir, "models")
    if os.path.exists(models_dir):
        print(f"Models dir contents: {os.listdir(models_dir)}", flush=True)
else:
    print(f"WARNING: PanoWan dir not found at {panowan_dir}", flush=True)

# Check uv
uv_check = subprocess.run(["which", "uv"], capture_output=True, text=True)
print(f"uv location: {uv_check.stdout.strip() or 'NOT FOUND'}", flush=True)


def handler(event):
    try:
        print(f"=== Job received: {event.get('id', 'unknown')} ===", flush=True)
        job_input = event["input"]
        prompt = job_input.get("prompt", "A beautiful mountain landscape at sunset")
        print(f"Prompt: {prompt[:100]}", flush=True)

        output_path = f"/tmp/output_{event['id']}.mp4"

        cmd = [
            "uv", "run", "panowan-test",
            "--wan-model-path", "./models/Wan-AI/Wan2.1-T2V-1.3B",
            "--lora-checkpoint-path", "./models/PanoWan/latest-lora.ckpt",
            "--output-path", output_path,
            "--prompt", prompt
        ]

        print(f"Running: {' '.join(cmd)}", flush=True)

        result = subprocess.run(
            cmd,
            cwd="/app/PanoWan",
            capture_output=True,
            text=True,
            timeout=1800  # 30 min timeout
        )

        print(f"Return code: {result.returncode}", flush=True)
        if result.stdout:
            print(f"Stdout: {result.stdout[-500:]}", flush=True)
        if result.stderr:
            print(f"Stderr: {result.stderr[-500:]}", flush=True)

        if result.returncode != 0:
            return {"error": f"Generation failed: {result.stderr[-500:]}"}

        if not os.path.exists(output_path):
            return {"error": "Output file not created"}

        with open(output_path, "rb") as f:
            video_bytes = f.read()

        video_base64 = base64.b64encode(video_bytes).decode("utf-8")
        os.remove(output_path)

        print(f"=== Job complete, video size: {len(video_bytes)} bytes ===", flush=True)

        return {
            "video_base64": video_base64,
            "prompt": prompt,
            "format": "mp4"
        }

    except subprocess.TimeoutExpired:
        print("ERROR: Generation timed out", flush=True)
        return {"error": "Generation timed out after 10 minutes"}
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        traceback.print_exc()
        return {"error": str(e)}


print("=== Registering handler with RunPod ===", flush=True)
runpod.serverless.start({"handler": handler})
