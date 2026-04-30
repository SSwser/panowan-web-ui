import os
import tempfile
import unittest

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
    }


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


class LoadResidentRuntimeTests(unittest.TestCase):
    def test_returns_dict_with_identity_and_pipeline(self) -> None:
        identity = PanoWanRuntimeIdentity(
            backend="panowan",
            wan_model_path="/models/wan",
            lora_checkpoint_path="/models/lora.ckpt",
        )
        loaded = runtime_provider.load_resident_runtime(identity)
        self.assertIs(loaded["identity"], identity)
        pipeline = loaded["pipeline"]
        self.assertIsNotNone(pipeline)
        self.assertEqual(pipeline["wan_model_path"], "/models/wan")


class RunJobInprocessTests(unittest.TestCase):
    def test_invalid_payload_raises_invalid_runner_job(self) -> None:
        identity = PanoWanRuntimeIdentity(
            backend="panowan",
            wan_model_path="/models/wan",
            lora_checkpoint_path="/models/lora.ckpt",
        )
        loaded = runtime_provider.load_resident_runtime(identity)
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_t2v_payload(os.path.join(tmp, "out.mp4"))
            del payload["negative_prompt"]
            with self.assertRaises(InvalidRunnerJob):
                runtime_provider.run_job_inprocess(loaded, payload)

    def test_valid_t2v_payload_writes_output_and_returns_ok(self) -> None:
        identity = PanoWanRuntimeIdentity(
            backend="panowan",
            wan_model_path="/models/wan",
            lora_checkpoint_path="/models/lora.ckpt",
        )
        loaded = runtime_provider.load_resident_runtime(identity)
        with tempfile.TemporaryDirectory() as tmp:
            output_path = os.path.join(tmp, "nested", "out.mp4")
            payload = _base_t2v_payload(output_path)
            result = runtime_provider.run_job_inprocess(loaded, payload)
            self.assertEqual(result, {"status": "ok", "output_path": output_path})
            self.assertTrue(os.path.exists(output_path))


class TeardownResidentRuntimeTests(unittest.TestCase):
    def test_clears_loaded_dict(self) -> None:
        loaded = {"identity": "x", "pipeline": {"a": 1}}
        runtime_provider.teardown_resident_runtime(loaded)
        self.assertEqual(loaded, {})

    def test_idempotent_on_already_empty_dict(self) -> None:
        loaded: dict = {}
        runtime_provider.teardown_resident_runtime(loaded)
        # Should not raise.
        runtime_provider.teardown_resident_runtime(loaded)
        self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()
