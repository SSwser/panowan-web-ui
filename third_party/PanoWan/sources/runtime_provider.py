"""PanoWan resident runtime provider — backend-root entrypoint.

Per spec §9 (docs/superpowers/specs/2026-04-30-platform-resident-runtime-host-design.md):
this module shares the same backend-root validation/dispatch semantics as
``runner.py`` so CLI and resident execution cannot diverge. ``validate_job``
and the runtime identity / failure classification helpers are imported from
``sources.runtime_adapter`` (single source of truth).

This module wires the resident host to the upstream ``diffsynth`` inference
pipeline (vendored from https://github.com/SSwser/PanoWan via
``app/backends/acquire.py`` + materialize). The resident host runs in-process
inside the Worker (spec §8: "the simplest boundary that preserves the
contract" — in-process is acceptable for the first implementation).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .runtime_adapter import (
    InvalidRunnerJob,
    PanoWanRuntimeIdentity,
    classify_runtime_failure as _classify_runtime_failure,
    runtime_identity_from_job as _runtime_identity_from_job,
    validate_job,
)

# Re-export so the platform builder resolves the SAME object as the adapter
# module (single source of truth for identity and failure classification).
runtime_identity_from_job = _runtime_identity_from_job
classify_runtime_failure = _classify_runtime_failure


# Upstream PanoWan ships ``diffsynth`` under ``vendor/src/diffsynth/`` after
# ``make setup-backends`` materializes it. The Worker process imports this
# provider before the materialized vendor tree is on ``sys.path`` (the worker
# venv only declares the platform's own deps), so we inject the vendor src
# root lazily at load time. Idempotent: re-injecting the same entry is a
# no-op for module resolution, so repeat loads (e.g. after eviction) stay
# cheap.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_VENDOR_SRC = _BACKEND_ROOT / "vendor" / "src"


def _ensure_vendor_on_sys_path() -> None:
    if not _VENDOR_SRC.is_dir():
        # Surface a clear error here — without vendor/, the import below would
        # raise a less-specific ``ModuleNotFoundError`` for ``diffsynth`` and
        # operators would not know to run ``make setup-backends``.
        raise FileNotFoundError(
            f"PanoWan vendor source tree missing at {_VENDOR_SRC}. "
            "Run `make setup-backends` to materialize the upstream diffsynth "
            "package before loading the resident runtime."
        )
    src_str = str(_VENDOR_SRC)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def load_resident_runtime(identity: PanoWanRuntimeIdentity) -> dict[str, Any]:
    """Build the WanVideoPipeline + LoRA on GPU and return it as the loaded runtime.

    Mirrors upstream ``diffsynth.scripts.test.test`` (the ``panowan-test``
    console script) so resident execution and CLI/debug execution converge on
    the same model construction sequence.
    """
    _ensure_vendor_on_sys_path()

    # Imports are local so that:
    #   * unit tests can stub ``diffsynth`` via ``sys.modules`` without
    #     installing torch+CUDA on the host,
    #   * import cost is paid only when the host actually decides to load the
    #     runtime (cold start), not at module import time.
    import torch  # noqa: PLC0415
    from diffsynth.models.model_manager import ModelManager  # noqa: PLC0415
    from diffsynth.pipelines.wan_video import WanVideoPipeline  # noqa: PLC0415

    wan_model_path = Path(identity.wan_model_path)
    lora_checkpoint_path = Path(identity.lora_checkpoint_path)
    if not wan_model_path.exists():
        raise FileNotFoundError(f"Wan2.1-T2V-1.3B model not found at {wan_model_path}")
    if not lora_checkpoint_path.exists():
        raise FileNotFoundError(f"LoRA checkpoint not found at {lora_checkpoint_path}")

    model_manager = ModelManager(device="cpu")
    model_manager.load_models(
        [
            str(wan_model_path / "diffusion_pytorch_model.safetensors"),
            str(wan_model_path / "models_t5_umt5-xxl-enc-bf16.pth"),
            str(wan_model_path / "Wan2.1_VAE.pth"),
        ],
        torch_dtype=torch.bfloat16,
    )
    model_manager.load_lora(str(lora_checkpoint_path), lora_alpha=1.0)

    pipe = WanVideoPipeline.from_model_manager(
        model_manager, torch_dtype=torch.bfloat16, device="cuda"
    )
    # ``num_persistent_param_in_dit=None`` mirrors upstream test.py — keeps the
    # full DiT resident on GPU for warm reuse instead of swapping per call.
    pipe.enable_vram_management(num_persistent_param_in_dit=None)

    return {
        "identity": identity,
        "model_manager": model_manager,
        "pipeline": pipe,
    }


def run_job_inprocess(loaded: dict[str, Any], job: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the job, run inference on the warm pipeline, write the video file.

    Validation matches ``runner.py`` exactly so CLI and resident execution
    enforce the same payload contract (spec §9).
    """
    payload = validate_job(dict(job))

    # Upstream PanoWan (https://github.com/SSwser/PanoWan) only ships a t2v
    # pipeline (``WanVideoPipeline`` + ``panowan-test`` console script). i2v
    # is part of the runner contract for forward compatibility but cannot be
    # served by the current resident runtime — fail fast with a clear contract
    # error instead of producing an empty file or silently falling back.
    if payload["task"] != "t2v":
        raise InvalidRunnerJob(
            f"task={payload['task']!r} is not supported by the resident PanoWan "
            "runtime; upstream diffsynth ships only the t2v pipeline"
        )

    pipe = loaded.get("pipeline")
    if pipe is None:
        # Defensive: if the host ever calls execute on a partially torn-down
        # runtime, surface a clear error instead of an AttributeError on None.
        raise RuntimeError("PanoWan resident runtime is not loaded")

    output_path = payload["output_path"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    resolution = payload["resolution"]
    width = resolution["width"]
    height = resolution["height"]
    # Upstream test.py asserts width == 2 * height (panoramic equirectangular).
    # Echo the same constraint at the contract boundary so a misconfigured
    # request produces a clear runner-level error instead of a torch assert.
    if width != height * 2:
        raise InvalidRunnerJob(
            "resolution.width must equal 2 * resolution.height for panoramic output"
        )

    pipe_kwargs: dict[str, Any] = {
        "prompt": payload["prompt"],
        "negative_prompt": payload.get("negative_prompt", ""),
        "num_inference_steps": payload.get("num_inference_steps", 50),
        "seed": payload.get("seed", 0),
        "tiled": True,
        "width": width,
        "height": height,
    }
    guidance_scale = payload.get("guidance_scale")
    if guidance_scale is not None:
        pipe_kwargs["cfg_scale"] = guidance_scale

    video = pipe(**pipe_kwargs)

    # save_video imported lazily here (not at load time) so that teardown +
    # idle-evict cycles do not hold a reference to diffsynth.data.
    from diffsynth.data import save_video  # noqa: PLC0415

    save_video(
        video,
        output_path,
        fps=15,
        quality=10,
        ffmpeg_params=["-crf", "18"],
    )

    return {"status": "ok", "output_path": output_path}


def teardown_resident_runtime(loaded: dict[str, Any]) -> None:
    """Drop runtime references and free GPU memory.

    The host calls teardown defensively during eviction and failure recovery,
    so this MUST NOT raise on already-empty dicts and MUST best-effort free
    GPU memory even if individual deletes fail.
    """
    if not loaded:
        return
    loaded.pop("pipeline", None)
    loaded.pop("model_manager", None)
    loaded.clear()

    # Best-effort GPU cleanup. Wrapped in try/except because torch may not be
    # importable in the unit-test path (no CUDA install on host) and teardown
    # must never propagate cleanup failures back to the host.
    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


__all__ = [
    "load_resident_runtime",
    "run_job_inprocess",
    "teardown_resident_runtime",
    "runtime_identity_from_job",
    "classify_runtime_failure",
    "InvalidRunnerJob",
    "PanoWanRuntimeIdentity",
]
