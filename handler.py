"""
PanoWan RunPod Serverless Handler
Generates 360° panoramic videos from text prompts using PanoWan.
"""

import runpod
import subprocess
import os
import base64
import tempfile


def handler(event):
    """
    Handler function for RunPod serverless.

    Input:
        - prompt (str): Text description for 360° panorama generation
        - output_format (str): "base64" or "url" (default: "base64")

    Returns:
        - video_base64 (str): Base64-encoded MP4 video
        - OR error message
    """
    try:
        job_input = event["input"]
        prompt = job_input.get("prompt", "A beautiful mountain landscape at sunset")

        # Create temp output path
        output_path = f"/tmp/output_{event['id']}.mp4"

        # Run PanoWan generation
        cmd = [
            "uv", "run", "panowan-test",
            "--wan-model-path", "/app/models/Wan-AI/Wan2.1-T2V-1.3B",
            "--lora-checkpoint-path", "/app/models/PanoWan/latest-lora.ckpt",
            "--output-path", output_path,
            "--prompt", prompt
        ]

        result = subprocess.run(
            cmd,
            cwd="/app/PanoWan",
            capture_output=True,
            text=True,
            timeout=600  # 10 min timeout
        )

        if result.returncode != 0:
            return {"error": f"Generation failed: {result.stderr[-500:]}"}

        if not os.path.exists(output_path):
            return {"error": "Output file not created"}

        # Read and encode the video
        with open(output_path, "rb") as f:
            video_bytes = f.read()

        video_base64 = base64.b64encode(video_bytes).decode("utf-8")

        # Cleanup
        os.remove(output_path)

        return {
            "video_base64": video_base64,
            "prompt": prompt,
            "format": "mp4"
        }

    except subprocess.TimeoutExpired:
        return {"error": "Generation timed out after 10 minutes"}
    except Exception as e:
        return {"error": str(e)}


runpod.serverless.start({"handler": handler})
