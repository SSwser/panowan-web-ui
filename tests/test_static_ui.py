import pathlib
import re
import unittest


INDEX_HTML = pathlib.Path("app/static/index.html").read_text(encoding="utf-8")


class StaticUiStateTests(unittest.TestCase):
    def test_status_badge_supports_canonical_states(self) -> None:
        self.assertIn('"claimed"', INDEX_HTML)
        self.assertIn('"cancelling"', INDEX_HTML)
        self.assertIn('"succeeded"', INDEX_HTML)
        self.assertIn('"cancelled"', INDEX_HTML)
        self.assertIn('排队中', INDEX_HTML)
        self.assertIn('正在取消', INDEX_HTML)
        self.assertIn('已完成', INDEX_HTML)
        self.assertIn('已取消', INDEX_HTML)

    def test_action_cell_uses_succeeded_not_completed(self) -> None:
        self.assertRegex(INDEX_HTML, r'if \(job\.status === "succeeded"\)')
        self.assertNotRegex(INDEX_HTML, r'if \(job\.status === "completed"\)')

    def test_claimed_and_cancelling_have_explicit_actions(self) -> None:
        self.assertIn('job.status === "claimed"', INDEX_HTML)
        self.assertIn('job.status === "cancelling"', INDEX_HTML)
        self.assertIn('正在取消…', INDEX_HTML)

    def test_worker_summary_markup_and_fetch_are_present(self) -> None:
        self.assertIn('id="worker-summary"', INDEX_HTML)
        self.assertIn('fetch("/workers/summary")', INDEX_HTML)
        self.assertIn('在线 Worker', INDEX_HTML)
        self.assertIn('生成中 Worker', INDEX_HTML)
        self.assertIn('排队任务', INDEX_HTML)

    def test_cancel_flow_has_cancelling_feedback(self) -> None:
        self.assertIn('正在取消', INDEX_HTML)
        self.assertIn('job.status === "cancelling"', INDEX_HTML)


class StaticUiCancellationGovernanceTests(unittest.TestCase):
    def read_static_html(self) -> str:
        return INDEX_HTML

    def test_worker_summary_uses_known_workers_and_stuck_cancelling_fields(self) -> None:
        html = self.read_static_html()
        self.assertIn('summary.known_workers', html)
        self.assertIn('summary.stuck_cancelling_workers', html)
        self.assertNotIn('summary.total_workers', html)

    def test_cancelling_action_cell_exposes_retry_and_escalation(self) -> None:
        html = self.read_static_html()
        self.assertIn('data-action="retry-cancel"', html)
        self.assertIn('data-action="escalate-cancel"', html)
        self.assertNotIn('force: isRunning', html)


if __name__ == "__main__":
    unittest.main()
