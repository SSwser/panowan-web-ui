import tempfile
import unittest

from app.engines import EngineRegistry
from app.engines.base import EngineResult
from app.engines.panowan import PanoWanEngine
from app.engines.upscale import UpscaleEngine
from app.jobs.local import LocalJobBackend
from app.jobs.workers import LocalWorkerRegistry
from app.runtime_host import ResidentRuntimeHost, RuntimeState, RuntimeStatusSnapshot
from app.worker_service import (
    _maybe_evict_idle,
    _resident_runtime_status,
    _startup_preload,
    build_host,
    publish_worker_state,
    run_one_job,
)


class FakeHost:
    """Records preload/maybe_evict_idle/run_job/status calls for assertions."""

    def __init__(self, status=RuntimeState.COLD):
        self.preload_calls = []
        self.evict_calls = []
        self.run_calls = []
        self._status_state = status
        self._has = {"panowan": True}

    def has_provider(self, key):
        return self._has.get(key, False)

    def preload(self, key, identity=None):
        self.preload_calls.append((key, identity))

    def maybe_evict_idle(self, key, idle_seconds):
        self.evict_calls.append((key, idle_seconds))
        return True

    def run_job(self, key, job):
        self.run_calls.append((key, dict(job)))
        return {"status": "ok", "output_path": job.get("output_path", "")}

    def status(self, key):
        if not self._has.get(key):
            return None
        return RuntimeStatusSnapshot(
            provider_key=key,
            state=self._status_state,
            identity=None,
            last_used_at=None,
            last_error=None,
        )


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

        registry = build_registry(ResidentRuntimeHost())
        self.assertIsInstance(registry.get("panowan"), PanoWanEngine)
        self.assertIsInstance(registry.get("upscale"), UpscaleEngine)

    def test_resolve_engine_routes_upscale_jobs(self) -> None:
        from app.worker_service import _resolve_engine, build_registry

        registry = build_registry(ResidentRuntimeHost())
        job = {"type": "upscale"}
        engine = _resolve_engine(registry, job)
        self.assertEqual(engine.name, "upscale")

    def test_resolve_engine_routes_generate_jobs_to_panowan(self) -> None:
        from app.worker_service import _resolve_engine, build_registry

        registry = build_registry(ResidentRuntimeHost())
        job = {"type": "generate"}
        engine = _resolve_engine(registry, job)
        self.assertEqual(engine.name, "panowan")

    def test_resolve_engine_rejects_unknown_job_type(self) -> None:
        from app.worker_service import _resolve_engine, build_registry

        registry = build_registry(ResidentRuntimeHost())
        with self.assertRaises(ValueError):
            _resolve_engine(registry, {"type": "unknown"})


class WorkerRuntimeTelemetryTests(unittest.TestCase):
    def test_publish_worker_state_includes_panowan_runtime_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            host = FakeHost(status=RuntimeState.WARM)
            engine_registry = EngineRegistry()
            engine = PanoWanEngine(host)
            engine_registry.register(engine)

            record = publish_worker_state(
                registry, "worker-test", engine_registry, host
            )

            self.assertEqual(record["panowan_runtime_status"], "warm")

    def test_publish_worker_state_returns_unknown_when_no_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            host = FakeHost()
            host._has = {}  # no panowan provider registered
            engine_registry = EngineRegistry()
            engine_registry.register(PanoWanEngine(host))

            record = publish_worker_state(
                registry, "worker-test", engine_registry, host
            )

            self.assertEqual(record["panowan_runtime_status"], "unknown")

    def test_resident_runtime_status_maps_each_state(self):
        for state, expected in [
            (RuntimeState.COLD, "cold"),
            (RuntimeState.LOADING, "loading"),
            (RuntimeState.WARM, "warm"),
            (RuntimeState.RUNNING, "running"),
            (RuntimeState.EVICTING, "evicting"),
            (RuntimeState.FAILED, "failed"),
        ]:
            host = FakeHost(status=state)
            self.assertEqual(_resident_runtime_status(host), expected)


class StartupPreloadTests(unittest.TestCase):
    def test_startup_preload_calls_host_when_setting_enabled(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        host = FakeHost()
        toggled = replace(base_settings, panowan_startup_preload=True)
        with patch("app.worker_service.settings", toggled):
            _startup_preload(host)
        self.assertEqual(host.preload_calls, [("panowan", None)])

    def test_startup_preload_skipped_when_setting_disabled(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        host = FakeHost()
        toggled = replace(base_settings, panowan_startup_preload=False)
        with patch("app.worker_service.settings", toggled):
            _startup_preload(host)
        self.assertEqual(host.preload_calls, [])

    def test_startup_preload_skipped_when_provider_missing(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        host = FakeHost()
        host._has = {}
        toggled = replace(base_settings, panowan_startup_preload=True)
        with patch("app.worker_service.settings", toggled):
            _startup_preload(host)
        self.assertEqual(host.preload_calls, [])

    def test_startup_preload_swallows_host_errors(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        class BoomHost(FakeHost):
            def preload(self, key, identity=None):
                raise RuntimeError("load failed")

        host = BoomHost()
        toggled = replace(base_settings, panowan_startup_preload=True)
        with patch("app.worker_service.settings", toggled):
            _startup_preload(host)  # must not raise


class MaybeEvictIdleTests(unittest.TestCase):
    def test_maybe_evict_idle_calls_host_when_threshold_positive(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        host = FakeHost()
        toggled = replace(base_settings, panowan_idle_evict_seconds=120.0)
        with patch("app.worker_service.settings", toggled):
            _maybe_evict_idle(host)
        self.assertEqual(host.evict_calls, [("panowan", 120.0)])

    def test_maybe_evict_idle_skipped_when_threshold_zero(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        host = FakeHost()
        toggled = replace(base_settings, panowan_idle_evict_seconds=0.0)
        with patch("app.worker_service.settings", toggled):
            _maybe_evict_idle(host)
        self.assertEqual(host.evict_calls, [])

    def test_maybe_evict_idle_skipped_when_provider_missing(self):
        from dataclasses import replace
        from unittest.mock import patch

        from app.settings import settings as base_settings

        host = FakeHost()
        host._has = {}
        toggled = replace(base_settings, panowan_idle_evict_seconds=120.0)
        with patch("app.worker_service.settings", toggled):
            _maybe_evict_idle(host)
        self.assertEqual(host.evict_calls, [])


class BuildHostTests(unittest.TestCase):
    def test_build_host_registers_panowan_provider_from_real_backend(self):
        # Exercises the full wiring contract against the real third_party/PanoWan
        # backend.toml — no mocks. Fast because it's just spec parsing + import.
        host = build_host()
        self.assertTrue(host.has_provider("panowan"))
