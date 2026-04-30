from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from app.settings import settings


class InvalidRunnerJob(ValueError):
    pass


_ALLOWED_FIELDS = frozenset(
    {
        "version",
        "task",
        "prompt",
        "negative_prompt",
        "output_path",
        "resolution",
        "num_frames",
        "seed",
        "num_inference_steps",
        "guidance_scale",
        "result_path",
        "input_image_path",
        "denoising_strength",
    }
)


_RUNTIME_ERROR_MARKERS = (
    "cuda out of memory",
    "cublas",
    "device-side assert",
    "illegal memory access",
)


@dataclass(frozen=True)
class PanoWanRuntimeIdentity:
    backend: str
    wan_model_path: str
    lora_checkpoint_path: str


def _require_absolute_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not os.path.isabs(value):
        raise InvalidRunnerJob(f"{field_name} must be an absolute path")
    return value


def validate_job(payload: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown:
        raise InvalidRunnerJob(f"Unknown fields: {', '.join(unknown)}")
    if payload.get("version") != "v1":
        raise InvalidRunnerJob("version must equal 'v1'")
    task = payload.get("task")
    if task not in {"t2v", "i2v"}:
        raise InvalidRunnerJob("task must be 't2v' or 'i2v'")
    if "prompt" not in payload:
        raise InvalidRunnerJob("prompt is required")
    if "negative_prompt" not in payload:
        raise InvalidRunnerJob("negative_prompt is required")
    resolution = payload.get("resolution")
    if not isinstance(resolution, dict):
        raise InvalidRunnerJob("resolution is required")
    for key in ("width", "height"):
        if not isinstance(resolution.get(key), int) or resolution[key] <= 0:
            raise InvalidRunnerJob(f"resolution.{key} must be a positive integer")
    if not isinstance(payload.get("num_frames"), int) or payload["num_frames"] <= 0:
        raise InvalidRunnerJob("num_frames must be a positive integer")
    payload["output_path"] = _require_absolute_path(
        payload.get("output_path"), "output_path"
    )
    if payload.get("result_path") is not None:
        payload["result_path"] = _require_absolute_path(
            payload.get("result_path"), "result_path"
        )
    if task == "i2v":
        payload["input_image_path"] = _require_absolute_path(
            payload.get("input_image_path"), "input_image_path"
        )
        denoising = payload.get("denoising_strength")
        if not isinstance(denoising, (int, float)) or denoising >= 1.0:
            raise InvalidRunnerJob("denoising_strength must be less than 1.0")
    else:
        if "input_image_path" in payload or "denoising_strength" in payload:
            raise InvalidRunnerJob(
                "input_image_path and denoising_strength are only valid for task=i2v"
            )
    return payload


def write_result(result_path: str | None, payload: dict[str, Any]) -> None:
    if not result_path:
        return
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def runtime_identity_from_job(job: dict[str, Any]) -> PanoWanRuntimeIdentity:
    # Identity intentionally ignores per-job fields like prompt/output_path so that
    # warm runtime reuse is keyed only on factors that change loaded resident state.
    return PanoWanRuntimeIdentity(
        backend="panowan",
        wan_model_path=settings.wan_model_path,
        lora_checkpoint_path=settings.lora_checkpoint_path,
    )


def classify_runtime_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    if isinstance(exc, (MemoryError, RuntimeError)) and any(
        marker in message for marker in _RUNTIME_ERROR_MARKERS
    ):
        return True
    return False
