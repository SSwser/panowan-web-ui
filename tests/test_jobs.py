import os
import tempfile
import unittest
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.cancellation import (
    CancellationCapability,
    CancellationContext,
    begin_cancellation,
    escalate_cancellation,
)
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

    def test_second_worker_cannot_mark_running_after_first_worker_owns_job(self):
        # Two workers race for the same job: only the worker holding the lease
        # may legally drive transitions. ADR 0010 §7 requires the second
        # worker's writes to be silently rejected, never overwriting state.
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {"job_id": "job-1", "status": "queued", "type": "generate"}
            )
            backend.claim_next_job(worker_id="worker-a")

            stolen = backend.mark_running("job-1", worker_id="worker-b")

            self.assertIsNone(stolen)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "claimed")
            self.assertEqual(job["worker_id"], "worker-a")

    def test_late_success_cannot_overwrite_newer_terminal_state(self):
        # A worker that returns success after cancellation has already been
        # finalised must not rewrite the cancelled terminal record.
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "output_path": f"{tmp}/out.mp4",
                }
            )
            backend.claim_next_job(worker_id="worker-a")
            backend.mark_running("job-1", "worker-a")
            backend.request_cancellation("job-1")
            backend.request_cancellation("job-1", finished=True)

            late = backend.mark_succeeded("job-1", "worker-a", f"{tmp}/out.mp4")

            self.assertIsNone(late)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "cancelled")

    def test_restore_never_fabricates_success_from_artifact_path(self):
        # The restore path must not promote an in-flight record to succeeded
        # just because an output_path string is present. Crashed workers leave
        # output_path set; recovery must mark such jobs failed instead.
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/jobs.json"
            os.makedirs(tmp, exist_ok=True)
            with open(path, "w") as handle:
                json.dump(
                    {
                        "jobs": {
                            "running": {
                                "job_id": "running",
                                "status": "running",
                                "type": "generate",
                                "output_path": f"{tmp}/out.mp4",
                                "worker_id": "worker-a",
                            }
                        }
                    },
                    handle,
                )

            restored = LocalJobBackend(path)
            restored.restore()

            job = restored.get_job("running")
            self.assertEqual(job["status"], "failed")
            self.assertEqual(
                job["error"], "Service restarted before the job completed"
            )


class CancellationGovernanceTests(unittest.TestCase):
    def test_begin_cancellation_adds_deadline_metadata(self) -> None:
        now = datetime(2026, 5, 1, 22, 5, tzinfo=UTC)
        capability = CancellationCapability(
            supports_soft_cancel=True,
            supports_escalated_cancel=True,
            default_cancel_timeout_sec=45,
            cancel_poll_interval_sec=1,
            cancel_checkpoint_granularity="checkpoint",
        )

        record = begin_cancellation(
            {
                "job_id": "job-1",
                "status": "running",
            },
            capability=capability,
            now=now,
        )

        self.assertEqual(record["status"], "cancelling")
        self.assertEqual(record["cancel_mode"], "soft")
        self.assertEqual(record["cancel_attempt"], 1)
        self.assertEqual(record["cancel_requested_at"], now.isoformat())
        self.assertEqual(
            record["cancel_deadline_at"],
            (now + timedelta(seconds=45)).isoformat(),
        )

    def test_escalate_cancellation_increments_attempt_and_mode(self) -> None:
        now = datetime(2026, 5, 1, 22, 6, tzinfo=UTC)
        capability = CancellationCapability(
            supports_soft_cancel=True,
            supports_escalated_cancel=True,
            default_cancel_timeout_sec=30,
            cancel_poll_interval_sec=1,
            cancel_checkpoint_granularity="checkpoint",
        )
        record = {
            "job_id": "job-1",
            "status": "cancelling",
            "cancel_mode": "soft",
            "cancel_attempt": 1,
            "cancel_requested_at": now.isoformat(),
            "cancel_deadline_at": (now + timedelta(seconds=30)).isoformat(),
        }

        escalated = escalate_cancellation(
            record,
            capability=capability,
            now=now + timedelta(seconds=10),
        )

        self.assertEqual(escalated["cancel_mode"], "escalated")
        self.assertEqual(escalated["cancel_attempt"], 2)
        self.assertGreater(
            escalated["cancel_deadline_at"],
            record["cancel_deadline_at"],
        )


class LocalJobCancellationFlowTests(unittest.TestCase):
    def make_backend(self) -> LocalJobBackend:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return LocalJobBackend(f"{self._tmp.name}/jobs.json")

    def make_running_job(self, backend: LocalJobBackend, *, worker_id: str) -> dict:
        backend.create_job(
            {"job_id": "job-1", "status": "queued", "type": "generate"}
        )
        backend.claim_next_job(worker_id=worker_id)
        return backend.mark_running("job-1", worker_id)

    def test_request_cancellation_sets_deadline_metadata(self) -> None:
        backend = self.make_backend()
        backend.create_job({"job_id": "job-1", "status": "queued", "type": "generate"})
        backend.claim_next_job(worker_id="worker-1")
        backend.mark_running("job-1", "worker-1")

        result = backend.request_cancellation("job-1", worker_id="worker-1")

        self.assertEqual(result["status"], "cancelling")
        self.assertEqual(result["cancel_mode"], "soft")
        self.assertIn("cancel_requested_at", result)
        self.assertIn("cancel_deadline_at", result)

    def test_escalate_cancellation_replaces_legacy_force_behavior(self) -> None:
        backend = self.make_backend()
        self.make_running_job(backend, worker_id="worker-1")
        backend.request_cancellation("job-1", worker_id="worker-1")

        result = backend.escalate_cancellation("job-1", worker_id="worker-1")

        self.assertEqual(result["status"], "cancelling")
        self.assertEqual(result["cancel_mode"], "escalated")
        self.assertEqual(result["cancel_attempt"], 2)

    def test_finalize_cancel_timeout_marks_failed(self) -> None:
        backend = self.make_backend()
        self.make_running_job(backend, worker_id="worker-1")
        backend.request_cancellation("job-1", worker_id="worker-1")

        result = backend.finalize_cancellation_timeout(
            "job-1", worker_id="worker-1", reason="cancel_timeout",
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "cancel_timeout")


if __name__ == "__main__":
    unittest.main()
