"""Unit tests for the platform resident runtime host.

These tests must NOT depend on GPU code, settings, or PanoWan modules.
A scripted ``FakeProvider`` exercises the host state machine.
"""

from __future__ import annotations

import logging
import threading
import unittest
from collections.abc import Hashable, Mapping
from typing import Any

from app.runtime_host import (
    ResidentRuntimeHost,
    RuntimeState,
    RuntimeStatusSnapshot,
)


class _FakeRuntime:
    def __init__(self, identity: Hashable) -> None:
        self.identity = identity
        self.torn_down = False


class FakeProvider:
    """Scriptable provider that records every host call."""

    def __init__(
        self,
        provider_key: str = "fake",
        *,
        default_identity: Hashable | None = None,
        has_default: bool = False,
    ) -> None:
        self.provider_key = provider_key
        self.calls: list[tuple[str, Any]] = []
        self.load_error: BaseException | None = None
        self.execute_error: BaseException | None = None
        self.execute_result: Mapping[str, Any] = {"ok": True}
        self.teardown_error: BaseException | None = None
        self.corrupting_excs: tuple[type[BaseException], ...] = (RuntimeError,)
        self._default_identity = default_identity
        if has_default:
            self.default_identity = self._default  # type: ignore[method-assign]

    def _default(self) -> Hashable | None:
        self.calls.append(("default_identity", None))
        return self._default_identity

    def runtime_identity_from_job(self, job: Mapping[str, Any]) -> Hashable:
        ident = job["identity"]
        self.calls.append(("identity_from_job", ident))
        return ident

    def load(self, identity: Hashable) -> Any:
        self.calls.append(("load", identity))
        if self.load_error is not None:
            raise self.load_error
        return _FakeRuntime(identity)

    def execute(self, loaded_runtime: Any, job: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(("execute", (loaded_runtime.identity, job.get("seq"))))
        if self.execute_error is not None:
            raise self.execute_error
        return dict(self.execute_result)

    def teardown(self, loaded_runtime: Any) -> None:
        self.calls.append(("teardown", loaded_runtime.identity))
        loaded_runtime.torn_down = True
        if self.teardown_error is not None:
            raise self.teardown_error

    def classify_failure(self, exc: BaseException) -> bool:
        self.calls.append(("classify_failure", type(exc).__name__))
        return isinstance(exc, self.corrupting_excs)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


class ResidentRuntimeHostTests(unittest.TestCase):
    def _build(
        self, **provider_kwargs: Any
    ) -> tuple[ResidentRuntimeHost, FakeProvider, _Clock]:
        clock = _Clock()
        host = ResidentRuntimeHost(clock=clock)
        provider = FakeProvider(**provider_kwargs)
        host.register_provider(provider)
        return host, provider, clock

    # ---- happy path / warm reuse -------------------------------------

    def test_cold_load_then_warm_reuse(self) -> None:
        host, provider, clock = self._build()
        result1 = host.run_job("fake", {"identity": "A", "seq": 1})
        clock.advance(5)
        result2 = host.run_job("fake", {"identity": "A", "seq": 2})

        self.assertEqual(result1, {"ok": True})
        self.assertEqual(result2, {"ok": True})
        load_calls = [c for c in provider.calls if c[0] == "load"]
        teardown_calls = [c for c in provider.calls if c[0] == "teardown"]
        self.assertEqual(len(load_calls), 1)
        self.assertEqual(teardown_calls, [])

        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.WARM)
        self.assertEqual(snap.identity, "A")
        self.assertEqual(snap.last_used_at, 1005.0)

    # ---- identity mismatch ------------------------------------------

    def test_identity_mismatch_evicts_and_reloads(self) -> None:
        host, provider, _ = self._build()
        host.run_job("fake", {"identity": "A", "seq": 1})
        host.run_job("fake", {"identity": "B", "seq": 2})

        kinds = [c[0] for c in provider.calls]
        # expected order: identity, load(A), execute, identity, teardown(A), load(B), execute
        self.assertIn("teardown", kinds)
        self.assertEqual(
            [c for c in provider.calls if c[0] == "load"],
            [("load", "A"), ("load", "B")],
        )
        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.identity, "B")
        self.assertEqual(snap.state, RuntimeState.WARM)

    # ---- corrupting failure -----------------------------------------

    def test_corrupting_failure_marks_failed_then_auto_resets(self) -> None:
        host, provider, _ = self._build()
        host.run_job("fake", {"identity": "A", "seq": 1})

        provider.execute_error = RuntimeError("CUDA OOM")
        with self.assertRaises(RuntimeError):
            host.run_job("fake", {"identity": "A", "seq": 2})

        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.FAILED)
        self.assertEqual(snap.last_error, "CUDA OOM")

        # Next call must auto-reset: teardown old, then reload, then execute.
        provider.execute_error = None
        result = host.run_job("fake", {"identity": "A", "seq": 3})
        self.assertEqual(result, {"ok": True})

        kinds = [c[0] for c in provider.calls]
        # teardown happened during auto-reset
        self.assertGreaterEqual(kinds.count("teardown"), 1)
        # two successful loads (initial + reset reload)
        self.assertEqual(kinds.count("load"), 2)
        snap2 = host.status("fake")
        assert snap2 is not None
        self.assertEqual(snap2.state, RuntimeState.WARM)

    # ---- non-corrupting failure -------------------------------------

    def test_non_corrupting_failure_keeps_warm(self) -> None:
        host, provider, _ = self._build()
        provider.corrupting_excs = (RuntimeError,)
        host.run_job("fake", {"identity": "A", "seq": 1})

        provider.execute_error = ValueError("bad prompt")
        with self.assertRaises(ValueError):
            host.run_job("fake", {"identity": "A", "seq": 2})

        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.WARM)
        # No teardown / reload required
        kinds = [c[0] for c in provider.calls]
        self.assertEqual(kinds.count("load"), 1)
        self.assertEqual(kinds.count("teardown"), 0)

    # ---- load failure -----------------------------------------------

    def test_load_failure_transitions_to_failed_and_propagates(self) -> None:
        host, provider, _ = self._build()
        provider.load_error = RuntimeError("init failed")
        with self.assertRaises(RuntimeError):
            host.run_job("fake", {"identity": "A", "seq": 1})

        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.FAILED)
        self.assertEqual(snap.last_error, "init failed")

    # ---- preload ----------------------------------------------------

    def test_preload_with_default_identity(self) -> None:
        host, provider, _ = self._build(default_identity="DEFAULT", has_default=True)
        host.preload("fake")
        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.WARM)
        self.assertEqual(snap.identity, "DEFAULT")

    def test_preload_raises_when_no_default_and_no_identity(self) -> None:
        host, _, _ = self._build()
        with self.assertRaises(ValueError):
            host.preload("fake")

    def test_preload_explicit_identity_warm_same_is_noop(self) -> None:
        host, provider, _ = self._build()
        host.preload("fake", "A")
        host.preload("fake", "A")
        self.assertEqual(
            [c for c in provider.calls if c[0] == "load"],
            [("load", "A")],
        )

    # ---- evict ------------------------------------------------------

    def test_evict_from_warm_transitions_cold_and_calls_teardown(self) -> None:
        host, provider, _ = self._build()
        host.run_job("fake", {"identity": "A", "seq": 1})
        host.evict("fake")
        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.COLD)
        self.assertIsNone(snap.identity)
        self.assertIn("teardown", [c[0] for c in provider.calls])

    def test_evict_from_cold_is_noop(self) -> None:
        host, provider, _ = self._build()
        host.evict("fake")
        self.assertNotIn("teardown", [c[0] for c in provider.calls])
        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.COLD)

    # ---- idle eviction ----------------------------------------------

    def test_maybe_evict_idle_respects_threshold(self) -> None:
        host, provider, clock = self._build()
        host.run_job("fake", {"identity": "A", "seq": 1})

        # Not idle yet
        clock.advance(10)
        self.assertFalse(host.maybe_evict_idle("fake", 60.0))

        # Past threshold
        clock.advance(100)
        self.assertTrue(host.maybe_evict_idle("fake", 60.0))
        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.COLD)
        self.assertIn("teardown", [c[0] for c in provider.calls])

    # ---- status_all -------------------------------------------------

    def test_status_all_includes_provider_after_registration(self) -> None:
        host, _, _ = self._build()
        all_status = host.status_all()
        self.assertIn("fake", all_status)
        snap = all_status["fake"]
        self.assertIsInstance(snap, RuntimeStatusSnapshot)
        self.assertEqual(snap.state, RuntimeState.COLD)
        self.assertIsNone(snap.identity)

    # ---- teardown errors swallowed ----------------------------------

    def test_teardown_exception_is_swallowed_during_eviction(self) -> None:
        host, provider, _ = self._build()
        host.run_job("fake", {"identity": "A", "seq": 1})
        provider.teardown_error = RuntimeError("teardown boom")
        with self.assertLogs("app.runtime_host", level="ERROR") as cm:
            host.evict("fake")  # must not raise
        self.assertTrue(any("teardown failed" in line for line in cm.output))

        snap = host.status("fake")
        assert snap is not None
        self.assertEqual(snap.state, RuntimeState.COLD)
        self.assertIsNone(snap.identity)

    # ---- unknown provider -------------------------------------------

    def test_unknown_provider_run_job_raises(self) -> None:
        host = ResidentRuntimeHost()
        with self.assertRaises(KeyError):
            host.run_job("nope", {"identity": "A"})

    def test_unknown_provider_status_returns_none(self) -> None:
        host = ResidentRuntimeHost()
        self.assertIsNone(host.status("nope"))

    # ---- per-provider concurrency ----------------------------------

    def test_different_providers_run_in_parallel(self) -> None:
        """Two providers must not serialize against each other.

        We block one provider's execute on a barrier; the other provider
        must still complete. This proves the host doesn't hold one global
        lock across provider calls.
        """
        host = ResidentRuntimeHost()
        slow = FakeProvider(provider_key="slow")
        fast = FakeProvider(provider_key="fast")
        gate = threading.Event()
        release = threading.Event()

        original_execute = slow.execute

        def slow_execute(loaded: Any, job: Mapping[str, Any]) -> Mapping[str, Any]:
            gate.set()
            release.wait(timeout=2.0)
            return original_execute(loaded, job)

        slow.execute = slow_execute  # type: ignore[method-assign]

        host.register_provider(slow)
        host.register_provider(fast)

        result_box: dict[str, Any] = {}

        def run_slow() -> None:
            result_box["slow"] = host.run_job("slow", {"identity": "S", "seq": 1})

        t = threading.Thread(target=run_slow)
        t.start()
        self.assertTrue(gate.wait(timeout=2.0), "slow provider never started")

        # While slow is mid-execute, fast must complete.
        result_box["fast"] = host.run_job("fast", {"identity": "F", "seq": 1})
        self.assertEqual(result_box["fast"], {"ok": True})

        release.set()
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(result_box["slow"], {"ok": True})


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
