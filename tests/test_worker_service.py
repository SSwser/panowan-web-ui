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
    build_registry,
    log_worker_summary,
    publish_worker_state,
    run_one_job,
)


class FakeHost:
    """Records preload/maybe_evict_idle/run_job/status calls for assertions."""

    def __init__(self, status=RuntimeState.COLD, provider_present: bool = True):
        self.preload_calls = []
        self.evict_calls = []
        self.run_calls = []
        self._status_state = status
        self._has = {"panowan": bool(provider_present)}

    def has_provider(self, key):
        return self._has.get(key, False)

    def preload(self, key, identity=None):
        self.preload_calls.append((key, identity))

    def maybe_evict_idle(self, key, idle_seconds):
        self.evict_calls.append((key, idle_seconds))
        return True

    def run_job(self, key, job, *, cancellation=None):
        self.run_calls.append((key, dict(job)))
        self.last_cancellation = cancellation
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

    def __init__(self, output_path: str = "output.mp4"):
        self._output_path = output_path

    def validate_runtime(self):
        return None

    def run(self, job):
        return EngineResult(
            output_path=job.get("output_path", self._output_path),
            metadata={"ok": True},
        )


class CancelledDuringRunEngine:
    name = "panowan"

    def __init__(self, backend: LocalJobBackend, worker_id: str):
        self.backend = backend
        self.worker_id = worker_id

    def run(self, job):
        # Simulate cooperative cancellation observed mid-run by routing
        # through the canonical request_cancellation entrypoint instead of
        # writing a raw status string.
        self.backend.request_cancellation(job["job_id"])
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
        # Simulate a force-cancel arriving while the engine is mid-run by
        # routing through the canonical cancellation entrypoint.
        self.backend.request_cancellation(job["job_id"])
        return EngineResult(output_path=job["output_path"], metadata={"ok": True})


def _registry_with(engine) -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(engine)
    return registry


class WorkerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Pre-existing tests in this class manage their own TemporaryDirectory
        # contexts and ignore self.jobs_path/self.workers_path. The shared
        # tmpdir below exists only for newer tests that use the _job_record
        # helper and the canonical paths.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.jobs_path = f"{self._tmpdir.name}/jobs.json"
        self.workers_path = f"{self._tmpdir.name}/workers.json"

    def _job_record(
        self,
        *,
        job_id: str,
        status: str = "queued",
        job_type: str = "generate",
        worker_id: str | None = None,
    ) -> dict:
        record = {
            "job_id": job_id,
            "status": status,
            "type": job_type,
            "output_path": f"{self._tmpdir.name}/outputs/output_{job_id}.mp4",
        }
        if worker_id is not None:
            record["worker_id"] = worker_id
        return record

    def test_run_one_job_logs_terminal_transition(self) -> None:
        backend = LocalJobBackend(self.jobs_path)
        backend.create_job(self._job_record(job_id="job-log", status="queued"))
        registry = _registry_with(FakeEngine(output_path="done.mp4"))
        with self.assertLogs("app.worker_service", level="INFO") as cm:
            run_one_job(backend, registry, worker_id="worker-1")
        joined = "\n".join(cm.output)
        self.assertIn("from_status=running", joined)
        self.assertIn("to_status=succeeded", joined)
        self.assertIn("job_id=job-log", joined)

    def test_publish_worker_state_logs_queue_summary(self) -> None:
        backend = LocalJobBackend(self.jobs_path)
        backend.create_job(self._job_record(job_id="queued-1", status="queued"))
        backend.create_job(
            self._job_record(job_id="running-1", status="running", worker_id="worker-1")
        )
        registry = LocalWorkerRegistry(self.workers_path)
        host = FakeHost(provider_present=True)
        engine_registry = _registry_with(FakeEngine(output_path="done.mp4"))
        with self.assertLogs("app.worker_service", level="INFO") as cm:
            log_worker_summary(
                backend, registry, host=host, engine_registry=engine_registry
            )
        joined = "\n".join(cm.output)
        self.assertIn("queued=1", joined)
        self.assertIn("running=1", joined)
        self.assertIn("online_workers=0", joined)

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
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["output_path"], f"{tmp}/outputs/output_job-1.mp4")
            self.assertIsNotNone(job["started_at"])

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
            # Engine signalled cooperative cancellation by moving running ->
            # cancelling; the worker must finalise the cancel rather than
            # rewriting it back to succeeded with a late completion report.
            self.assertEqual(job["status"], "cancelled")

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
            # Pre-empt the worker by claiming and cancelling the job before
            # run_one_job() observes the queue.
            backend.claim_next_job(worker_id="other-worker")
            backend.request_cancellation("job-1")
            backend.request_cancellation("job-1", finished=True)

            class ShouldNotRunEngine:
                name = "panowan"

                def run(self, job):
                    raise AssertionError("engine.run should not be called")

            worked = run_one_job(
                backend, _registry_with(ShouldNotRunEngine()), worker_id="worker-a"
            )

            self.assertFalse(worked)
            job = backend.get_job("job-1")
            self.assertEqual(job["status"], "cancelled")

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

    def test_run_one_job_keeps_cancelled_terminal_if_cancel_wins(
        self,
    ):
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
            # ADR 0010: a late success report cannot overwrite a terminal
            # cancellation that was accepted while the engine was running.
            self.assertEqual(job["status"], "cancelled")
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

            # cancel_queued_job is the queued-only entry point. Once a worker
            # owns the job, cancellation must flow through the cooperative
            # cancelling state via request_cancellation, not be quietly
            # rewritten by the queued-only helper.
            self.assertFalse(cancelled)
            self.assertEqual(job["status"], "claimed")
            self.assertEqual(job["worker_id"], "worker-a")
            self.assertIsNone(job["error"])
            self.assertIsNone(job["finished_at"])

    def test_cancel_queued_job_marks_job_cancelled_atomically(self):
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
            self.assertEqual(job["status"], "cancelled")
            self.assertIsNone(job["error"])
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


class MultiEngineRegistryTests(unittest.TestCase):
    def test_build_registry_contains_panowan_when_provider_registered(self) -> None:
        registry = build_registry(FakeHost())
        self.assertIsInstance(registry.get("panowan"), PanoWanEngine)
        self.assertIsInstance(registry.get("upscale"), UpscaleEngine)

    def test_build_registry_skips_panowan_when_provider_missing(self) -> None:
        host = FakeHost()
        host._has = {}
        registry = build_registry(host)
        with self.assertRaises(KeyError):
            registry.get("panowan")
        self.assertIsInstance(registry.get("upscale"), UpscaleEngine)

    def test_resolve_engine_routes_generate_jobs_only_when_provider_registered(self) -> None:
        from app.worker_service import _resolve_engine

        self.assertEqual(
            _resolve_engine(build_registry(FakeHost()), {"type": "generate"}).name,
            "panowan",
        )

        host = FakeHost()
        host._has = {}
        with self.assertRaises(KeyError):
            _resolve_engine(build_registry(host), {"type": "generate"})

    def test_publish_worker_state_omits_panowan_capabilities_when_provider_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            host = FakeHost()
            host._has = {}
            record = publish_worker_state(
                registry, "worker-test", build_registry(host), host
            )

        self.assertEqual(record["capabilities"], ["upscale"])
        self.assertEqual(record["panowan_runtime_status"], "unknown")

    def test_publish_worker_state_includes_future_panowan_capabilities_when_provider_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            host = FakeHost()
            record = publish_worker_state(
                registry, "worker-test", build_registry(host), host
            )

        self.assertEqual(sorted(record["capabilities"]), ["i2v", "t2v", "upscale"])
        self.assertEqual(record["panowan_runtime_status"], "cold")

    def test_publish_worker_state_returns_unknown_for_manual_registry_misalignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = LocalWorkerRegistry(f"{tmp}/workers.json")
            host = FakeHost()
            host._has = {}
            engine_registry = EngineRegistry()
            engine_registry.register(PanoWanEngine(host))

            record = publish_worker_state(
                registry, "worker-test", engine_registry, host
            )

        self.assertEqual(record["panowan_runtime_status"], "unknown")
        self.assertIn("t2v", record["capabilities"])
        self.assertIn("i2v", record["capabilities"])


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


class PanowanCancellationTests(unittest.TestCase):
    def test_panowan_engine_wraps_legacy_callable_into_probe(self) -> None:
        # Legacy job dicts that only carry ``_should_cancel`` must still reach
        # the host as a probe so providers see the structured contract even
        # before the worker injects ``_cancellation_probe`` directly.
        class RecordingHost:
            def __init__(self) -> None:
                self.provider_key = "panowan"
                self.seen_cancellation = None

            def run_job(self, provider_key, payload, *, cancellation=None):
                self.seen_cancellation = cancellation
                assert provider_key == "panowan"
                return {"output_path": "out.mp4"}

        engine = PanoWanEngine(host=RecordingHost())
        result = engine.run({
            "job_id": "job-1",
            "payload": {"task": "t2v", "prompt": "demo"},
            "_should_cancel": lambda: False,
        })

        self.assertEqual(result.output_path, "out.mp4")
        forwarded = engine._host.seen_cancellation
        self.assertIsNotNone(forwarded)
        self.assertFalse(forwarded.should_stop())


class RuntimeCancellationContractTests(unittest.TestCase):
    def test_panowan_engine_passes_cancellation_probe_to_host(self) -> None:
        from app.cancellation import (
            CallbackCancellationProbe,
            CancellationContext,
        )
        from app.engines.panowan import PanoWanEngine

        seen = {}

        class FakeHost:
            def run_job(self, provider_key, payload, *, cancellation=None):
                seen["cancellation"] = cancellation
                return {"output_path": payload.get("output_path", "out.mp4")}

        engine = PanoWanEngine(FakeHost())
        ctx = CancellationContext(
            job_id="job-1",
            worker_id="worker-1",
            mode="soft",
            requested_at="2026-05-01T14:00:00+00:00",
            deadline_at="2026-05-01T14:00:45+00:00",
            attempt=1,
        )
        probe = CallbackCancellationProbe(context=ctx, stop_check=lambda: False)
        job = {
            "job_id": "job-1",
            "type": "generate",
            "prompt": "demo",
            "task": "t2v",
            "worker_id": "worker-1",
            "output_path": "out.mp4",
            "_cancellation_probe": probe,
        }

        engine.run(job)

        self.assertIs(seen["cancellation"], probe)
        self.assertEqual(seen["cancellation"].context.mode, "soft")
        self.assertEqual(
            seen["cancellation"].context.deadline_at,
            "2026-05-01T14:00:45+00:00",
        )

    def test_runtime_provider_observes_cancel_probe_instead_of_discarding_it(
        self,
    ) -> None:
        # Assert the provider observes the probe BEFORE reaching the
        # "runtime is not loaded" guard. We cannot import diffsynth in the
        # test environment, so we rely on the very first checkpoint being
        # the cancellation poll: passing ``loaded={"pipeline": None}`` would
        # otherwise raise RuntimeError; with a stop-on-first probe the
        # function must return ``cancelled`` first.
        from app.cancellation import (
            CallbackCancellationProbe,
            CancellationContext,
        )
        import third_party.PanoWan.sources.runtime_provider as provider_mod

        ctx = CancellationContext(
            job_id="job-1",
            worker_id="worker-1",
            mode="soft",
            requested_at="",
            deadline_at="",
            attempt=1,
        )
        probe = CallbackCancellationProbe(context=ctx, stop_check=lambda: True)

        result = provider_mod.run_job_inprocess(
            loaded={"pipeline": None},
            job={
                "version": "v1",
                "task": "t2v",
                "prompt": "demo",
                "output_path": "/tmp/out.mp4",
                "resolution": {"width": 2048, "height": 1024},
                "num_frames": 81,
            },
            cancellation=probe,
        )

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["output_path"], "/tmp/out.mp4")
