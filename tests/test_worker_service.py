import tempfile
import unittest

from app.engines.base import EngineResult
from app.jobs.local import LocalJobBackend
from app.worker_service import run_one_job


class FakeEngine:
    name = "fake"
    capabilities = ("generate",)

    def validate_runtime(self):
        return None

    def run(self, job):
        return EngineResult(output_path=job["output_path"], metadata={"ok": True})


class WorkerServiceTests(unittest.TestCase):
    def test_run_one_job_claims_and_completes_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "output_path": f"{tmp}/outputs/output_job-1.mp4",
                }
            )

            worked = run_one_job(backend, FakeEngine(), worker_id="worker-a")

            self.assertTrue(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["output_path"], f"{tmp}/outputs/output_job-1.mp4")

    def test_run_one_job_returns_false_when_queue_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")

            self.assertFalse(run_one_job(backend, FakeEngine(), worker_id="worker-a"))
