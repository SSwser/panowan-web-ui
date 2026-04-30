import unittest
from unittest import mock

from app.engines.base import EngineResult
from app.engines.panowan import PanoWanEngine
from app.engines.registry import EngineRegistry
from app.engines.upscale import UpscaleEngine
from app.runtime_host import ResidentRuntimeHost
from app.settings import settings


class _FakeHost:
    """Minimal stand-in for ResidentRuntimeHost used in engine-level tests."""

    def __init__(self, run_result=None):
        self.run_calls = []
        self._run_result = run_result or {
            "status": "ok",
            "output_path": "/tmp/o.mp4",
        }

    def run_job(self, provider_key, job):
        self.run_calls.append((provider_key, dict(job)))
        return self._run_result


def _make_engine(host=None) -> PanoWanEngine:
    return PanoWanEngine(host or _FakeHost())


class EngineRegistryTests(unittest.TestCase):
    def test_register_and_get_engine(self):
        engine = _make_engine()
        registry = EngineRegistry()
        registry.register(engine)

        self.assertIs(registry.get("panowan"), engine)
        self.assertIn("t2v", registry.get("panowan").capabilities)

    def test_unknown_engine_raises_key_error(self):
        registry = EngineRegistry()
        with self.assertRaises(KeyError):
            registry.get("missing")

    def test_register_duplicate_engine_raises_value_error(self):
        engine = _make_engine()
        registry = EngineRegistry()
        registry.register(engine)

        with self.assertRaises(ValueError):
            registry.register(engine)

    def test_all_returns_registered_engines(self):
        engine = _make_engine()
        registry = EngineRegistry()
        registry.register(engine)

        self.assertEqual(registry.all(), (engine,))


class EngineResultTests(unittest.TestCase):
    def test_metadata_defaults_to_new_dict(self):
        first = EngineResult(output_path="/tmp/a.mp4")
        second = EngineResult(output_path="/tmp/b.mp4")

        first.metadata["ok"] = True

        self.assertEqual(second.metadata, {})


class PanoWanEngineTests(unittest.TestCase):
    def test_validate_runtime_is_noop(self) -> None:
        # Engine no longer probes runtime files; runtime errors surface from
        # the host on first load, not from validate_runtime().
        engine = _make_engine()
        # Must not raise even when no real runtime assets exist.
        self.assertIsNone(engine.validate_runtime())

    def test_engine_run_delegates_to_host(self):
        host = _FakeHost(
            run_result={"status": "ok", "output_path": "/tmp/o.mp4"}
        )
        engine = PanoWanEngine(host)

        with mock.patch("app.engines.panowan.build_runner_payload") as mock_payload:
            payload = {
                "version": "v1",
                "task": "t2v",
                "prompt": "sky",
                "negative_prompt": "blur",
                "output_path": "/tmp/o.mp4",
                "resolution": {"width": 896, "height": 448},
                "num_frames": 81,
            }
            mock_payload.return_value = payload
            result = engine.run({"prompt": "sky", "negative_prompt": "blur"})

        self.assertEqual(host.run_calls, [("panowan", payload)])
        self.assertEqual(result.output_path, "/tmp/o.mp4")
        self.assertEqual(result.metadata, {})


class UpscaleEngineTests(unittest.TestCase):
    def test_upscale_engine_has_correct_name_and_capabilities(self) -> None:
        engine = UpscaleEngine()
        self.assertEqual(engine.name, "upscale")
        self.assertEqual(engine.capabilities, ("upscale",))

    @mock.patch("app.engines.upscale.os.path.exists", return_value=True)
    def test_validate_runtime_passes_when_dirs_exist(self, mock_exists) -> None:
        engine = UpscaleEngine()
        with mock.patch(
            "app.engines.upscale.get_available_upscale_backends",
            return_value={"realesrgan-animevideov3": object()},
        ):
            engine.validate_runtime()  # Should not raise

    @mock.patch("app.engines.upscale.os.path.exists", return_value=False)
    def test_validate_runtime_raises_when_dirs_missing(self, mock_exists) -> None:
        engine = UpscaleEngine()
        with self.assertRaises(FileNotFoundError):
            engine.validate_runtime()

    @mock.patch("app.engines.upscale.os.path.exists", return_value=True)
    def test_validate_runtime_fails_when_no_backend_available(
        self, mock_exists
    ) -> None:
        engine = UpscaleEngine()
        with mock.patch(
            "app.engines.upscale.get_available_upscale_backends",
            return_value={},
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                engine.validate_runtime()
        self.assertIn("No available upscale backends", str(ctx.exception))

    @mock.patch("app.engines.upscale.upscale_video")
    def test_run_delegates_to_upscale_video(self, mock_upscale) -> None:
        mock_upscale.return_value = {
            "output_path": "/app/runtime/outputs/output_up.mp4",
            "model": "realesrgan-animevideov3",
            "scale": 2,
        }
        engine = UpscaleEngine()

        def cancel_probe() -> bool:
            return False

        result = engine.run(
            {
                "source_output_path": "/app/runtime/outputs/output_src.mp4",
                "output_path": "/app/runtime/outputs/output_up.mp4",
                "_should_cancel": cancel_probe,
                "upscale_params": {
                    "model": "realesrgan-animevideov3",
                    "scale": 2,
                },
            }
        )
        self.assertEqual(
            result,
            EngineResult(
                output_path="/app/runtime/outputs/output_up.mp4",
                metadata={},
            ),
        )
        mock_upscale.assert_called_once()
        self.assertEqual(
            mock_upscale.call_args.kwargs,
            {
                "input_path": "/app/runtime/outputs/output_src.mp4",
                "output_path": "/app/runtime/outputs/output_up.mp4",
                "model": "realesrgan-animevideov3",
                "scale": 2,
                "target_width": None,
                "target_height": None,
                "engine_dir": settings.upscale_engine_dir,
                "weights_dir": settings.upscale_weights_dir,
                "timeout_seconds": 1800,
                "should_cancel": cancel_probe,
            },
        )


class PanoWanEngineCapabilitiesTests(unittest.TestCase):
    def test_panowan_engine_does_not_have_upscale_capability(self) -> None:
        engine = _make_engine()
        self.assertNotIn("upscale", engine.capabilities)
        self.assertEqual(engine.capabilities, ("t2v", "i2v"))


class PanoWanEngineConstructorTests(unittest.TestCase):
    def test_engine_accepts_real_resident_host(self) -> None:
        # Construction with a real (empty) host must work without raising.
        host = ResidentRuntimeHost()
        engine = PanoWanEngine(host)
        self.assertIs(engine._host, host)


if __name__ == "__main__":
    unittest.main()
