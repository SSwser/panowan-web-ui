import os
import tempfile
import unittest

from third_party.PanoWan.sources.runtime_adapter import (
    InvalidRunnerJob,
    classify_runtime_failure,
    runtime_identity_from_job,
    validate_job,
)

_TMP = tempfile.gettempdir()
_OUT = os.path.join(_TMP, "out.mp4")
_OUT2 = os.path.join(_TMP, "other.mp4")
_IMG = os.path.join(_TMP, "img.png")


class ValidateJobTests(unittest.TestCase):
    def _base_payload(self) -> dict:
        return {
            "version": "v1",
            "task": "t2v",
            "prompt": "sky",
            "negative_prompt": "blur",
            "output_path": _OUT,
            "resolution": {"width": 896, "height": 448},
            "num_frames": 81,
        }

    def test_valid_t2v_payload_passes(self) -> None:
        payload = self._base_payload()
        result = validate_job(payload)
        self.assertEqual(result["task"], "t2v")

    def test_missing_negative_prompt_defaults_empty_string(self) -> None:
        payload = self._base_payload()
        del payload["negative_prompt"]
        result = validate_job(payload)
        self.assertEqual(result["negative_prompt"], "")

    def test_unknown_fields_raise(self) -> None:
        payload = {**self._base_payload(), "extra_field": "bad"}
        with self.assertRaisesRegex(InvalidRunnerJob, "Unknown fields"):
            validate_job(payload)

    def test_i2v_requires_input_image_path(self) -> None:
        payload = {
            **self._base_payload(),
            "task": "i2v",
            "denoising_strength": 0.7,
        }
        with self.assertRaisesRegex(InvalidRunnerJob, "input_image_path"):
            validate_job(payload)

    def test_t2v_rejects_i2v_only_fields(self) -> None:
        payload = {**self._base_payload(), "input_image_path": _IMG}
        with self.assertRaisesRegex(InvalidRunnerJob, "only valid for task=i2v"):
            validate_job(payload)


class RuntimeIdentityTests(unittest.TestCase):
    def _base_job(self) -> dict:
        return {
            "version": "v1",
            "task": "t2v",
            "prompt": "sky",
            "negative_prompt": "blur",
            "output_path": _OUT,
            "resolution": {"width": 896, "height": 448},
            "num_frames": 81,
        }

    def test_prompt_change_does_not_change_identity(self) -> None:
        j1 = validate_job(self._base_job())
        j2 = validate_job({**self._base_job(), "prompt": "ocean"})
        self.assertEqual(
            runtime_identity_from_job(j1), runtime_identity_from_job(j2)
        )

    def test_output_path_change_does_not_change_identity(self) -> None:
        j1 = validate_job(self._base_job())
        j2 = validate_job({**self._base_job(), "output_path": _OUT2})
        self.assertEqual(
            runtime_identity_from_job(j1), runtime_identity_from_job(j2)
        )


class FailureClassificationTests(unittest.TestCase):
    def test_oom_error_is_runtime_corrupting(self) -> None:
        self.assertTrue(
            classify_runtime_failure(RuntimeError("CUDA out of memory"))
        )

    def test_file_not_found_is_not_runtime_corrupting(self) -> None:
        self.assertFalse(
            classify_runtime_failure(FileNotFoundError("missing file"))
        )

    def test_cublas_error_is_runtime_corrupting(self) -> None:
        self.assertTrue(
            classify_runtime_failure(RuntimeError("cuBLAS error occurred"))
        )

    def test_illegal_memory_access_is_runtime_corrupting(self) -> None:
        self.assertTrue(
            classify_runtime_failure(
                RuntimeError("illegal memory access was encountered")
            )
        )


if __name__ == "__main__":
    unittest.main()
