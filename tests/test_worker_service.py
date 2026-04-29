import tempfile
import unittest

from app.engines import EngineRegistry
from app.engines.base import EngineResult
from app.engines.panowan import PanoWanEngine
from app.engines.upscale import UpscaleEngine
from app.jobs.local import LocalJobBackend
from app.jobs.workers import LocalWorkerRegistry
from app.worker_service import publish_worker_state, run_one_job


class FakeEngine:
    name = "panowan"
    capabilities = ("generate",)

    def validate_runtime(self):
        return None

    def run(self, job):
        return EngineResult(output_path=job["output_path"], metadata={"ok": True})


class CancelledDuringRunEngine:
    name = "panowan"

    def __init__(self, backend: LocalJobBackend, worker_id: str):
        self.backend = backend
        self.worker_id = worker_id

    def run(self, job):
        self.backend.update_job(
            job["job_id"],
            status="failed",
            error="Cancelled by user",
        )
        return EngineResult(output_path=job["output_path"], metadata={"ok": True})


class FailingEngine:
    name = "panowan"
    capabilities = ("generate",)

    def validate_runtime(self):
        return None

    def run(self, job):
        raise RuntimeError("engine exploded")


class ForceCancelledAfterSuccessfulRunEngine:
    name = "panowan"
    capabilities = ("generate",)

    def __init__(self, backend: LocalJobBackend):
        self.backend = backend

    def validate_runtime(self):
        return None

    def run(self, job):
        self.backend.update_job(
            job["job_id"],
            status="failed",
            error="Cancelled by user",
            finished_at="cancelled-at",
        )
        return EngineResult(output_path=job["output_path"], metadata={"ok": True})


def _registry_with(engine) -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(engine)
    return registry


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

            worked = run_one_job(
                backend, _registry_with(FakeEngine()), worker_id="worker-a"
            )

            self.assertTrue(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["output_path"], f"{tmp}/outputs/output_job-1.mp4")

    def test_run_one_job_does_not_overwrite_cancelled_job_after_engine_run(self):
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

            worked = run_one_job(
                backend,
                _registry_with(CancelledDuringRunEngine(backend, "worker-a")),
                worker_id="worker-a",
            )

            self.assertTrue(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Cancelled by user")

    def test_run_one_job_skips_execution_when_job_no_longer_running(self):
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
            claimed = backend.claim_next_job(worker_id="worker-a")
            self.assertIsNotNone(claimed)
            backend.update_job("job-1", status="failed", error="Cancelled by user")

            class ShouldNotRunEngine:
                name = "panowan"

                def run(self, job):
                    raise AssertionError("engine.run should not be called")

            worked = run_one_job(
                backend, _registry_with(ShouldNotRunEngine()), worker_id="worker-a"
            )

            self.assertFalse(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Cancelled by user")

    def test_run_one_job_returns_false_when_queue_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")

            self.assertFalse(
                run_one_job(backend, _registry_with(FakeEngine()), worker_id="worker-a")
            )

    def test_run_one_job_marks_failure_without_re_raising_engine_error(self):
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

            worked = run_one_job(
                backend, _registry_with(FailingEngine()), worker_id="worker-a"
            )

            self.assertTrue(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "engine exploded")

    def test_run_one_job_completes_success_if_engine_finishes_before_cancel_is_observed(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            output_path = f"{tmp}/outputs/output_job-1.mp4"
            backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "output_path": output_path,
                }
            )

            worked = run_one_job(
                backend,
                _registry_with(ForceCancelledAfterSuccessfulRunEngine(backend)),
                worker_id="worker-a",
            )

            self.assertTrue(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["output_path"], output_path)
            self.assertIsNone(job["error"])
            self.assertIsNotNone(job["finished_at"])

    def test_cancel_queued_job_is_rejected_if_worker_claimed_it_first(self):
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
            backend.claim_next_job(worker_id="worker-a")

            cancelled = backend.cancel_queued_job("job-1")
            job = backend.get_job("job-1")

            self.assertFalse(cancelled)
            self.assertEqual(job["status"], "running")
            self.assertEqual(job["worker_id"], "worker-a")
            self.assertIsNone(job["error"])
            self.assertIsNone(job["finished_at"])

    def test_cancel_queued_job_marks_job_failed_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalJobBackend(f"{tmp}/jobs.json")
            output_path = f"{tmp}/outputs/output_job-1.mp4"
            backend.create_job(
                {
                    "job_id": "job-1",
                    "status": "queued",
                    "type": "generate",
                    "output_path": output_path,
                }
            )

            cancelled = backend.cancel_queued_job("job-1")
            job = backend.get_job("job-1")

            self.assertTrue(cancelled)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"], "Cancelled by user")
            self.assertIsNotNone(job["finished_at"])
            self.assertIsNone(job["started_at"])
            self.assertIsNone(job["worker_id"])
            self.assertEqual(job["output_path"], output_path)
            self.assertEqual(job["download_url"], "/jobs/job-1/download")
            self.assertEqual(job["job_id"], "job-1")
            self.assertEqual(job["type"], "generate")
            self.assertEqual(job["params"], {})
            self.assertEqual(job["prompt"], "")
            self.assertIsNone(job["source_job_id"])
            self.assertIsNone(job["upscale_params"])
            self.assertIsNotNone(job["created_at"])
            self.assertIsNone(job.get("payload"))
            self.assertIsNone(job.get("source_output_path"))
            self.assertIsNone(job["worker_id"])
            self.assertIsNone(job["started_at"])


class MultiEngineRegistryTests(unittest.TestCase):
    def test_build_registry_contains_both_engines(self) -> None:
        from app.worker_service import build_registry

        registry = build_registry()
        self.assertIsInstance(registry.get("panowan"), PanoWanEngine)
        self.assertIsInstance(registry.get("upscale"), UpscaleEngine)

    def test_resolve_engine_routes_upscale_jobs(self) -> None:
        from app.worker_service import _resolve_engine, build_registry

        registry = build_registry()
        job = {"type": "upscale"}
        engine = _resolve_engine(registry, job)
        self.assertEqual(engine.name, "upscale")

    def test_resolve_engine_routes_generate_jobs_to_panowan(self) -> None:
        from app.worker_service import _resolve_engine, build_registry

        registry = build_registry()
        job = {"type": "generate"}
        engine = _resolve_engine(registry, job)
        self.assertEqual(engine.name, "panowan")

    def test_resolve_engine_rejects_unknown_job_type(self) -> None:
        from app.worker_service import _resolve_engine, build_registry

        registry = build_registry()
        with self.assertRaises(ValueError):
            _resolve_engine(registry, {"type": "unknown"})


class WorkerRuntimeTelemetryTests(unittest.TestCase):
    def test_publish_worker_state_includes_panowan_runtime_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            engine_registry = EngineRegistry()
            engine = PanoWanEngine()
            engine_registry.register(engine)

            record = publish_worker_state(
                registry, "worker-test", engine_registry
            )

            self.assertIn("panowan_runtime_status", record)
