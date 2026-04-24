import unittest
from unittest import mock

from app.engines.base import EngineResult
from app.engines.panowan import PanoWanEngine
from app.engines.registry import EngineRegistry


class EngineRegistryTests(unittest.TestCase):
    def test_register_and_get_engine(self):
        engine = PanoWanEngine()
        registry = EngineRegistry()
        registry.register(engine)

        self.assertIs(registry.get("panowan"), engine)
        self.assertIn("t2v", registry.get("panowan").capabilities)

    def test_unknown_engine_raises_key_error(self):
        registry = EngineRegistry()
        with self.assertRaises(KeyError):
            registry.get("missing")


class PanoWanEngineTests(unittest.TestCase):
    @mock.patch("app.engines.panowan.generate_video")
    def test_run_generate_delegates_to_generator(self, generate_video):
        generate_video.return_value = {"output_path": "/app/runtime/outputs/output_job-1.mp4"}
        engine = PanoWanEngine()

        result = engine.run({"job_id": "job-1", "type": "generate", "prompt": "sky"})

        self.assertEqual(
            result,
            EngineResult(output_path="/app/runtime/outputs/output_job-1.mp4", metadata={}),
        )
        generate_video.assert_called_once()
