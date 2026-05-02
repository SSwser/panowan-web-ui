"""Tests for the PanoWan resident runtime provider.

The provider's real ``load_resident_runtime`` constructs a ``diffsynth``
``WanVideoPipeline`` on GPU. Tests on the CI/host path cannot install torch
+ flash-attn + the full vendor tree, so we inject a fake ``diffsynth``
package via ``sys.modules`` and a fake ``vendor/src`` directory so the
provider's sys.path-injection contract still runs.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from third_party.PanoWan.sources import runtime_adapter, runtime_provider
from third_party.PanoWan.sources.runtime_adapter import (
    InvalidRunnerJob,
    PanoWanRuntimeIdentity,
)


def _base_t2v_payload(output_path: str) -> dict:
    return {
        "version": "v1",
        "task": "t2v",
        "prompt": "sky",
        "negative_prompt": "blur",
        "output_path": output_path,
        "resolution": {"width": 896, "height": 448},
        "num_frames": 81,
        "num_inference_steps": 25,
        "seed": 7,
    }


class _FakePipeline:
    """Stand-in for ``diffsynth.pipelines.wan_video.WanVideoPipeline`` instances."""

    def __init__(self) -> None:
        self.last_call_kwargs: dict | None = None
        self.vram_management_called = False
        self.vram_management_kwargs: dict | None = None

    def enable_vram_management(self, **kwargs) -> None:
        self.vram_management_called = True
        self.vram_management_kwargs = kwargs

    def __call__(self, **kwargs):
        self.last_call_kwargs = kwargs
        # Real pipelines return a list of frames; tests only need a sentinel
        # the fake save_video can recognize.
        return ["frame-0", "frame-1"]


class _FakeModelManager:
    instances: list["_FakeModelManager"] = []

    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self.loaded_models: list[str] = []
        self.loaded_dtype = None
        self.lora_path: str | None = None
        self.lora_alpha: float | None = None
        _FakeModelManager.instances.append(self)

    def load_models(self, paths, torch_dtype=None) -> None:
        self.loaded_models = list(paths)
        self.loaded_dtype = torch_dtype

    def load_lora(self, path: str, lora_alpha: float = 1.0) -> None:
        self.lora_path = path
        self.lora_alpha = lora_alpha


class _PipelineFactory:
    """Captures from_model_manager calls and returns a single _FakePipeline."""

    def __init__(self) -> None:
        self.last_manager: _FakeModelManager | None = None
        self.last_kwargs: dict | None = None
        self.pipeline = _FakePipeline()

    def from_model_manager(self, manager, **kwargs):
        self.last_manager = manager
        self.last_kwargs = kwargs
        return self.pipeline


class _SaveVideoRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, video, output_path: str, **kwargs) -> None:
        self.calls.append(
            {"video": video, "output_path": output_path, "kwargs": kwargs}
        )
        # Real save_video writes a binary mp4 file. The contract this provider
        # must uphold is "the output path exists with non-empty content after
        # successful execution", so write a small marker so existence checks
        # downstream still pass.
        with open(output_path, "wb") as handle:
            handle.write(b"\x00fake-mp4")


def _install_fake_diffsynth(
    pipeline_factory: _PipelineFactory,
    save_video: _SaveVideoRecorder,
) -> dict[str, types.ModuleType]:
    """Register a minimal fake ``diffsynth`` package on ``sys.modules``."""
    _FakeModelManager.instances = []

    diffsynth = types.ModuleType("diffsynth")
    data_mod = types.ModuleType("diffsynth.data")
    data_mod.save_video = save_video  # type: ignore[attr-defined]

    models_pkg = types.ModuleType("diffsynth.models")
    model_manager_mod = types.ModuleType("diffsynth.models.model_manager")
    model_manager_mod.ModelManager = _FakeModelManager  # type: ignore[attr-defined]

    pipelines_pkg = types.ModuleType("diffsynth.pipelines")
    wan_video_mod = types.ModuleType("diffsynth.pipelines.wan_video")
    wan_video_mod.WanVideoPipeline = pipeline_factory  # type: ignore[attr-defined]

    return {
        "diffsynth": diffsynth,
        "diffsynth.data": data_mod,
        "diffsynth.models": models_pkg,
        "diffsynth.models.model_manager": model_manager_mod,
        "diffsynth.pipelines": pipelines_pkg,
        "diffsynth.pipelines.wan_video": wan_video_mod,
    }


class _DiffsynthHarness:
    """Context manager that installs fake diffsynth + a fake vendor/src dir."""

    def __init__(self) -> None:
        self.pipeline_factory = _PipelineFactory()
        self.save_video = _SaveVideoRecorder()
        self._modules = _install_fake_diffsynth(self.pipeline_factory, self.save_video)
        self._vendor_dir: tempfile.TemporaryDirectory | None = None
        self._patches: list = []

    def __enter__(self) -> "_DiffsynthHarness":
        for name, module in self._modules.items():
            sys.modules[name] = module
        # Provide a fake vendor src dir so _ensure_vendor_on_sys_path passes.
        self._vendor_dir = tempfile.TemporaryDirectory()
        fake_src = Path(self._vendor_dir.name) / "src"
        fake_src.mkdir()
        self._patches.append(
            mock.patch.object(runtime_provider, "_VENDOR_SRC", fake_src)
        )
        # Provide a fake torch module so the provider's local imports succeed.
        torch_mod = types.ModuleType("torch")
        torch_mod.bfloat16 = "bfloat16-sentinel"  # type: ignore[attr-defined]

        class _Cuda:
            @staticmethod
            def is_available() -> bool:
                return False

            @staticmethod
            def empty_cache() -> None:
                return None

        torch_mod.cuda = _Cuda()  # type: ignore[attr-defined]
        sys.modules["torch"] = torch_mod
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for patch in self._patches:
            patch.stop()
        for name in list(self._modules):
            sys.modules.pop(name, None)
        sys.modules.pop("torch", None)
        if self._vendor_dir is not None:
            self._vendor_dir.cleanup()


def _identity(model_dir: str, lora_path: str) -> PanoWanRuntimeIdentity:
    return PanoWanRuntimeIdentity(
        backend="panowan",
        wan_model_path=model_dir,
        lora_checkpoint_path=lora_path,
    )


def _materialize_weights(tmp: str) -> tuple[str, str]:
    model_dir = os.path.join(tmp, "wan")
    os.makedirs(model_dir)
    for filename in (
        "diffusion_pytorch_model.safetensors",
        "models_t5_umt5-xxl-enc-bf16.pth",
        "Wan2.1_VAE.pth",
    ):
        Path(model_dir, filename).touch()
    lora_path = os.path.join(tmp, "lora.ckpt")
    Path(lora_path).touch()
    return model_dir, lora_path


class ReExportIdentityTests(unittest.TestCase):
    def test_runtime_identity_from_job_is_same_object(self) -> None:
        # Single source of truth — the provider must re-export, not redefine.
        self.assertIs(
            runtime_provider.runtime_identity_from_job,
            runtime_adapter.runtime_identity_from_job,
        )

    def test_classify_runtime_failure_is_same_object(self) -> None:
        self.assertIs(
            runtime_provider.classify_runtime_failure,
            runtime_adapter.classify_runtime_failure,
        )


class VendorSysPathTests(unittest.TestCase):
    def test_load_raises_when_vendor_src_missing(self) -> None:
        identity = _identity("/models/wan", "/models/lora.ckpt")
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with mock.patch.object(runtime_provider, "_VENDOR_SRC", missing):
                with self.assertRaisesRegex(FileNotFoundError, "vendor source"):
                    runtime_provider.load_resident_runtime(identity)


class _AlwaysCancelledProbe:
    def should_stop_now(self) -> bool:
        return True

    def should_escalate(self) -> bool:
        return False


class PanoWanRuntimeProviderContractTests(unittest.TestCase):
    def test_interrupt_capabilities_are_truthful_for_current_provider(self) -> None:
        capabilities = runtime_provider.interrupt_capabilities()
        self.assertEqual(
            capabilities,
            {
                "load_cancel_awareness": True,
                "execute_soft_interrupt": True,
                "execute_step_interrupt": False,
                "execute_escalated_interrupt": False,
                "requires_reset_after_failed_interrupt": False,
            },
        )

    def test_load_resident_runtime_accepts_cancellation_argument(self) -> None:
        identity = _identity("/models/wan", "/models/lora.ckpt")
        with self.assertRaisesRegex(RuntimeError, "cancelled_before_load"):
            runtime_provider.load_resident_runtime(
                identity,
                cancellation=_AlwaysCancelledProbe(),
                context=None,
            )


class LoadResidentRuntimeTests(unittest.TestCase):
    def test_load_constructs_pipeline_with_expected_files_and_lora(self) -> None:
        with _DiffsynthHarness() as harness, tempfile.TemporaryDirectory() as tmp:
            model_dir, lora_path = _materialize_weights(tmp)
            identity = _identity(model_dir, lora_path)

            loaded = runtime_provider.load_resident_runtime(identity)

            self.assertIs(loaded["identity"], identity)
            self.assertIs(loaded["pipeline"], harness.pipeline_factory.pipeline)
            self.assertIsNotNone(loaded["model_manager"])

            manager = loaded["model_manager"]
            self.assertEqual(
                manager.loaded_models,
                [
                    str(Path(model_dir) / "diffusion_pytorch_model.safetensors"),
                    str(Path(model_dir) / "models_t5_umt5-xxl-enc-bf16.pth"),
                    str(Path(model_dir) / "Wan2.1_VAE.pth"),
                ],
            )
            self.assertEqual(manager.lora_path, lora_path)
            self.assertEqual(manager.lora_alpha, 1.0)
            self.assertTrue(harness.pipeline_factory.pipeline.vram_management_called)
            self.assertEqual(
                harness.pipeline_factory.pipeline.vram_management_kwargs,
                {"num_persistent_param_in_dit": None},
            )

    def test_load_raises_when_wan_model_missing(self) -> None:
        with _DiffsynthHarness(), tempfile.TemporaryDirectory() as tmp:
            identity = _identity(os.path.join(tmp, "no-wan"), os.path.join(tmp, "x"))
            with self.assertRaises(FileNotFoundError):
                runtime_provider.load_resident_runtime(identity)

    def test_load_raises_when_lora_missing(self) -> None:
        with _DiffsynthHarness(), tempfile.TemporaryDirectory() as tmp:
            model_dir = os.path.join(tmp, "wan")
            os.makedirs(model_dir)
            identity = _identity(model_dir, os.path.join(tmp, "missing-lora.ckpt"))
            with self.assertRaises(FileNotFoundError):
                runtime_provider.load_resident_runtime(identity)


class RunJobInprocessTests(unittest.TestCase):
    def test_invalid_payload_raises_invalid_runner_job(self) -> None:
        with _DiffsynthHarness(), tempfile.TemporaryDirectory() as tmp:
            model_dir, lora_path = _materialize_weights(tmp)
            loaded = runtime_provider.load_resident_runtime(
                _identity(model_dir, lora_path)
            )
            payload = _base_t2v_payload(os.path.join(tmp, "out.mp4"))
            payload["task"] = "bogus"
            with self.assertRaises(InvalidRunnerJob):
                runtime_provider.run_job_inprocess(loaded, payload)

    def test_i2v_rejected_with_clear_message(self) -> None:
        with _DiffsynthHarness(), tempfile.TemporaryDirectory() as tmp:
            model_dir, lora_path = _materialize_weights(tmp)
            loaded = runtime_provider.load_resident_runtime(
                _identity(model_dir, lora_path)
            )
            payload = _base_t2v_payload(os.path.join(tmp, "out.mp4"))
            payload["task"] = "i2v"
            payload["input_image_path"] = os.path.join(tmp, "img.png")
            payload["denoising_strength"] = 0.7
            with self.assertRaisesRegex(InvalidRunnerJob, "i2v"):
                runtime_provider.run_job_inprocess(loaded, payload)

    def test_resolution_must_be_panoramic(self) -> None:
        with _DiffsynthHarness(), tempfile.TemporaryDirectory() as tmp:
            model_dir, lora_path = _materialize_weights(tmp)
            loaded = runtime_provider.load_resident_runtime(
                _identity(model_dir, lora_path)
            )
            payload = _base_t2v_payload(os.path.join(tmp, "out.mp4"))
            payload["resolution"] = {"width": 512, "height": 512}
            with self.assertRaisesRegex(InvalidRunnerJob, "panoramic"):
                runtime_provider.run_job_inprocess(loaded, payload)

    def test_valid_t2v_calls_pipeline_and_saves_video(self) -> None:
        with _DiffsynthHarness() as harness, tempfile.TemporaryDirectory() as tmp:
            model_dir, lora_path = _materialize_weights(tmp)
            loaded = runtime_provider.load_resident_runtime(
                _identity(model_dir, lora_path)
            )
            output_path = os.path.join(tmp, "nested", "out.mp4")
            payload = _base_t2v_payload(output_path)
            payload["guidance_scale"] = 6.0

            result = runtime_provider.run_job_inprocess(loaded, payload)

            self.assertEqual(result, {"status": "ok", "output_path": output_path})

            pipe = harness.pipeline_factory.pipeline
            self.assertEqual(
                pipe.last_call_kwargs,
                {
                    "prompt": "sky",
                    "negative_prompt": "blur",
                    "num_inference_steps": 25,
                    "seed": 7,
                    "tiled": True,
                    "width": 896,
                    "height": 448,
                    "cfg_scale": 6.0,
                },
            )
            self.assertEqual(len(harness.save_video.calls), 1)
            saved = harness.save_video.calls[0]
            self.assertEqual(saved["output_path"], output_path)
            self.assertEqual(
                saved["kwargs"],
                {
                    "fps": 15,
                    "quality": 10,
                    "ffmpeg_params": ["-crf", "18"],
                },
            )
            self.assertTrue(os.path.exists(output_path))
            self.assertGreater(os.path.getsize(output_path), 0)

    def test_run_without_loaded_pipeline_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_t2v_payload(os.path.join(tmp, "out.mp4"))
            with self.assertRaises(RuntimeError):
                runtime_provider.run_job_inprocess(
                    {"identity": object()},
                    payload,
                )


class TeardownResidentRuntimeTests(unittest.TestCase):
    def test_clears_loaded_dict(self) -> None:
        loaded = {"identity": "x", "pipeline": object(), "model_manager": object()}
        runtime_provider.teardown_resident_runtime(loaded)
        self.assertEqual(loaded, {})

    def test_idempotent_on_already_empty_dict(self) -> None:
        loaded: dict = {}
        runtime_provider.teardown_resident_runtime(loaded)
        runtime_provider.teardown_resident_runtime(loaded)
        self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()
