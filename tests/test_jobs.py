import tempfile
import unittest

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

    def test_claim_next_job_marks_it_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )

            claimed = backend.claim_next_job(worker_id="worker-a")

            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["job_id"], "job-1")
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(claimed["worker_id"], "worker-a")
            self.assertIsNone(backend.claim_next_job(worker_id="worker-a"))

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
            backend.claim_next_job(worker_id="w")  # claims j1

            completed = backend.complete_job("j1", "/out/j1.mp4")
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["output_path"], "/out/j1.mp4")
            self.assertIsNotNone(completed["finished_at"])

            failed = backend.fail_job("j2", "boom")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"], "boom")
            self.assertIsNotNone(failed["finished_at"])

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


if __name__ == "__main__":
    unittest.main()
