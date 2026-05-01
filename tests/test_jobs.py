import os
import tempfile
import unittest
import json
from unittest.mock import patch

from app.jobs.local import LocalJobBackend


class LocalJobBackendTests(unittest.TestCase):
    def test_create_update_and_list_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            created = backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "prompt": "mountain",
                    "params": {"width": 896, "height": 448},
                    "output_path": f"{tmp}/outputs/output_job-1.mp4",
                }
            )
            self.assertEqual(created["status"], "queued")

            updated = backend.update_job("job-1", status="running", started_at="now")
            self.assertEqual(updated["status"], "running")
            self.assertEqual(updated["started_at"], "now")

            listed = backend.list_jobs()
            self.assertEqual([job["job_id"] for job in listed], ["job-1"])

    def test_claim_next_job_marks_it_claimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )

            claimed = backend.claim_next_job(worker_id="worker-a")

            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["job_id"], "job-1")
            self.assertEqual(claimed["status"], "claimed")
            self.assertIsNone(claimed["started_at"])
            self.assertEqual(claimed["worker_id"], "worker-a")
            self.assertIsNone(backend.claim_next_job(worker_id="worker-a"))

    def test_mark_running_transitions_claimed_to_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )
            backend.claim_next_job(worker_id="worker-a")

            running = backend.mark_running("job-1", "worker-a")

            self.assertIsNotNone(running)
            self.assertEqual(running["status"], "running")
            self.assertIsNotNone(running["started_at"])

    def test_mark_running_rejects_wrong_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )
            backend.claim_next_job(worker_id="worker-a")

            self.assertIsNone(backend.mark_running("job-1", "worker-b"))

    def test_restore_marks_incomplete_jobs_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/jobs.json"
            backend = LocalJobBackend(path)
            backend.create_job(
                {"job_id": "job-1", "status": "running", "type": "generate"}
            )

            restored = LocalJobBackend(path)
            restored.restore()
            job = restored.get_job("job-1")

            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Service restarted before the job completed")

    def test_complete_and_fail_finalizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job({"job_id": "j1", "status": "queued", "type": "generate"})
            backend.create_job({"job_id": "j2", "status": "queued", "type": "generate"})
            backend.claim_next_job(worker_id="w")  # j1 -> claimed
            backend.mark_running("j1", "w")  # claimed -> running
            backend.claim_next_job(worker_id="w")  # j2 -> claimed
            backend.mark_running("j2", "w")  # claimed -> running

            completed = backend.mark_succeeded("j1", "w", "/out/j1.mp4")
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(completed["output_path"], "/out/j1.mp4")
            self.assertIsNotNone(completed["finished_at"])

            failed = backend.mark_failed("j2", "w", "boom")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"], "boom")
            self.assertIsNotNone(failed["finished_at"])

    def test_delete_failed_jobs_removes_records_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = f"{tmp}/outputs/output_j1.mp4"
            os.makedirs(f"{tmp}/outputs", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write("partial")

            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {
                    "job_id": "j1",
                    "status": "failed",
                    "type": "generate",
                    "output_path": output_path,
                }
            )
            backend.create_job(
                {"job_id": "j2", "status": "succeeded", "type": "generate"}
            )

            deleted = backend.delete_failed_jobs()

            self.assertEqual(deleted, ["j1"])
            self.assertIsNone(backend.get_job("j1"))
            self.assertIsNotNone(backend.get_job("j2"))
            self.assertFalse(os.path.exists(output_path))

    def test_restore_keeps_incomplete_jobs_in_dev_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/jobs.json"
            backend = LocalJobBackend(path)
            backend.create_job(
                {"job_id": "job-1", "status": "running", "type": "generate"}
            )

            restored = LocalJobBackend(path)
            with patch.dict("os.environ", {"DEV_MODE": "1"}, clear=False):
                restored.restore()
            job = restored.get_job("job-1")

            self.assertEqual(job["status"], "running")
            self.assertIsNone(job["error"])

    def test_update_job_unknown_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job({"job_id": "j1", "status": "queued", "type": "generate"})
            with self.assertRaises(ValueError):
                backend.update_job("j1", staus="running")  # typo

    def test_update_job_missing_raises_key_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            with self.assertRaises(KeyError):
                backend.update_job("nope", status="running")

    def test_create_job_collision_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job({"job_id": "j1", "status": "queued", "type": "generate"})
            with self.assertRaises(ValueError):
                backend.create_job(
                    {"job_id": "j1", "status": "queued", "type": "generate"}
                )

    def test_create_job_does_not_alias_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            params = {"width": 896}
            backend.create_job(
                {
                    "job_id": "j1",
                    "status": "queued",
                    "type": "generate",
                    "params": params,
                }
            )
            params["width"] = 1920  # mutate caller's copy
            stored = backend.get_job("j1")
            self.assertEqual(stored["params"], {"width": 896})

    def test_separate_backend_instances_reload_latest_disk_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/jobs.json"
            first = LocalJobBackend(path)
            second = LocalJobBackend(path)

            first.create_job({"job_id": "j1", "status": "queued", "type": "generate"})

            self.assertEqual(second.get_job("j1")["status"], "queued")
            with self.assertRaises(ValueError):
                second.create_job(
                    {"job_id": "j1", "status": "queued", "type": "generate"}
                )

    def test_cancel_queued_job_marks_job_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )

            self.assertTrue(backend.cancel_queued_job("job-1"))
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "cancelled")
            self.assertIsNone(job["error"])
            self.assertIsNotNone(job["finished_at"])

    def test_request_cancellation_on_running_job_marks_cancelling(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )
            backend.claim_next_job(worker_id="w")
            backend.mark_running("job-1", "w")

            updated = backend.request_cancellation("job-1")

            self.assertIsNotNone(updated)
            self.assertEqual(updated["status"], "cancelling")

    def test_request_cancellation_finalizes_cancelling_to_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )
            backend.claim_next_job(worker_id="w")
            backend.mark_running("job-1", "w")
            backend.request_cancellation("job-1")

            finalized = backend.request_cancellation("job-1", finished=True)

            self.assertIsNotNone(finalized)
            self.assertEqual(finalized["status"], "cancelled")
            self.assertIsNotNone(finalized["finished_at"])

    def test_request_cancellation_refuses_terminal_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )
            backend.claim_next_job(worker_id="w")
            backend.mark_running("job-1", "w")
            backend.mark_succeeded("job-1", "w", "/out.mp4")

            self.assertIsNone(backend.request_cancellation("job-1"))
            self.assertEqual(backend.get_job("job-1")["status"], "succeeded")

    def test_restore_normalizes_legacy_completed_and_cancelled_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/jobs.json"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "jobs": {
                            "done": {
                                "job_id": "done",
                                "status": "completed",
                                "type": "generate",
                            },
                            "cancelled": {
                                "job_id": "cancelled",
                                "status": "failed",
                                "error": "Cancelled by user",
                                "type": "generate",
                            },
                            "real-failure": {
                                "job_id": "real-failure",
                                "status": "failed",
                                "error": "engine exploded",
                                "type": "generate",
                            },
                        }
                    },
                    handle,
                )

            restored = LocalJobBackend(path)
            restored.restore()

            self.assertEqual(restored.get_job("done")["status"], "succeeded")
            self.assertEqual(restored.get_job("cancelled")["status"], "cancelled")
            self.assertIsNone(restored.get_job("cancelled")["error"])
            self.assertEqual(restored.get_job("real-failure")["status"], "failed")
            self.assertEqual(
                restored.get_job("real-failure")["error"], "engine exploded"
            )


if __name__ == "__main__":
    unittest.main()
