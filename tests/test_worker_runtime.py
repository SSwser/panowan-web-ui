import unittest
from unittest import mock

from app.worker_runtime import PanoWanRuntimeController


class ControllerStateTests(unittest.TestCase):
    def _make_controller(self, load_fn=None, teardown_fn=None):
        load_fn = load_fn or mock.Mock(return_value=object())
        teardown_fn = teardown_fn or mock.Mock()
        return PanoWanRuntimeController(load_fn=load_fn, teardown_fn=teardown_fn)

    def test_initial_status_is_cold(self) -> None:
        ctrl = self._make_controller()
        self.assertEqual(ctrl.status_snapshot()["status"], "cold")

    def test_ensure_loaded_transitions_to_warm(self) -> None:
        runtime = object()
        identity = object()
        load_fn = mock.Mock(return_value=runtime)
        ctrl = self._make_controller(load_fn=load_fn)
        ctrl.ensure_loaded(identity)
        self.assertEqual(ctrl.status_snapshot()["status"], "warm")
        load_fn.assert_called_once_with(identity)

    def test_run_job_reuses_runtime_when_identity_matches(self) -> None:
        runtime = object()
        identity = "same-identity"
        load_fn = mock.Mock(return_value=runtime)
        execute_fn = mock.Mock(
            return_value={"status": "ok", "output_path": "/tmp/o.mp4"}
        )
        ctrl = self._make_controller(load_fn=load_fn)

        ctrl.ensure_loaded(identity)
        ctrl.run_job({"prompt": "a"}, identity=identity, execute_fn=execute_fn)
        ctrl.run_job({"prompt": "b"}, identity=identity, execute_fn=execute_fn)

        self.assertEqual(load_fn.call_count, 1)
        self.assertEqual(ctrl.status_snapshot()["status"], "warm")

    def test_run_job_reloads_when_identity_changes(self) -> None:
        runtime_a = object()
        runtime_b = object()
        load_fn = mock.Mock(side_effect=[runtime_a, runtime_b])
        execute_fn = mock.Mock(
            return_value={"status": "ok", "output_path": "/tmp/o.mp4"}
        )
        teardown_fn = mock.Mock()
        ctrl = self._make_controller(load_fn=load_fn, teardown_fn=teardown_fn)

        ctrl.ensure_loaded("identity-a")
        ctrl.run_job(
            {"prompt": "a"}, identity="identity-b", execute_fn=execute_fn
        )

        self.assertEqual(load_fn.call_count, 2)
        teardown_fn.assert_called_once()

    def test_run_job_transitions_to_failed_on_runtime_corrupting_error(
        self,
    ) -> None:
        runtime = object()
        load_fn = mock.Mock(return_value=runtime)

        def bad_execute(runtime, job):
            raise RuntimeError("CUDA out of memory")

        ctrl = self._make_controller(load_fn=load_fn)
        ctrl.ensure_loaded("identity-a")

        with self.assertRaises(RuntimeError):
            ctrl.run_job(
                {"prompt": "test"},
                identity="identity-a",
                execute_fn=bad_execute,
                is_runtime_corrupting=lambda exc: True,
            )

        self.assertEqual(ctrl.status_snapshot()["status"], "failed")

    def test_run_job_stays_warm_on_non_corrupting_error(self) -> None:
        runtime = object()
        load_fn = mock.Mock(return_value=runtime)

        def bad_execute(runtime, job):
            raise FileNotFoundError("missing input")

        ctrl = self._make_controller(load_fn=load_fn)
        ctrl.ensure_loaded("identity-a")

        with self.assertRaises(FileNotFoundError):
            ctrl.run_job(
                {"prompt": "test"},
                identity="identity-a",
                execute_fn=bad_execute,
                is_runtime_corrupting=lambda exc: False,
            )

        self.assertEqual(ctrl.status_snapshot()["status"], "warm")

    def test_evict_tears_down_loaded_runtime(self) -> None:
        runtime = object()
        load_fn = mock.Mock(return_value=runtime)
        teardown_fn = mock.Mock()
        ctrl = self._make_controller(load_fn=load_fn, teardown_fn=teardown_fn)
        ctrl.ensure_loaded("id")
        ctrl.evict()
        teardown_fn.assert_called_once_with(runtime)
        self.assertEqual(ctrl.status_snapshot()["status"], "cold")

    def test_reset_from_failed_transitions_to_cold(self) -> None:
        ctrl = self._make_controller()
        # Force into failed state to verify reset() is the only way out.
        ctrl._state = "failed"
        ctrl.reset()
        self.assertEqual(ctrl.status_snapshot()["status"], "cold")


if __name__ == "__main__":
    unittest.main()
