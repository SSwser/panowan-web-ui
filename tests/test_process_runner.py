import subprocess
import sys
import unittest

from app.cancellation import CancellationContext, RuntimeCancellationProbe
from app.process_runner import ProcessCancelledError, run_cancellable_process


class AlwaysCancelProbe(RuntimeCancellationProbe):
    @property
    def context(self) -> CancellationContext:
        return CancellationContext(
            job_id="job-1",
            worker_id="worker-1",
            mode="soft",
            requested_at="now",
            deadline_at="later",
            attempt=1,
        )

    def should_stop_now(self) -> bool:
        return True

    def should_escalate(self) -> bool:
        return False


class ProcessRunnerCancellationTests(unittest.TestCase):
    def test_runtime_cancellation_probe_stops_process(self) -> None:
        with self.assertRaises(ProcessCancelledError):
            run_cancellable_process(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout_seconds=10,
                cancellation=AlwaysCancelProbe(),
                text=True,
            )

    def test_timeout_still_raises_timeout_expired(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            run_cancellable_process(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout_seconds=0,
                text=True,
            )


if __name__ == "__main__":
    unittest.main()
