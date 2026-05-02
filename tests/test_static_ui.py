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
        self.assertIn('正在取消', INDEX_HTML)

    def test_worker_summary_markup_and_fetch_are_present(self) -> None:
        self.assertIn('id="worker-summary"', INDEX_HTML)
        self.assertIn('fetch("/workers/summary")', INDEX_HTML)
        self.assertIn('id="worker-online-count"', INDEX_HTML)
        self.assertIn('id="worker-loading-count"', INDEX_HTML)
        self.assertIn('id="worker-busy-count"', INDEX_HTML)
        self.assertIn('id="jobs-queued-count"', INDEX_HTML)
        self.assertIn('id="jobs-generating-count"', INDEX_HTML)
        self.assertIn('id="workers-available-capacity"', INDEX_HTML)
        self.assertNotIn('id="workers-capacity-available"', INDEX_HTML)
        self.assertNotIn('id="worker-online-metric"', INDEX_HTML)
        self.assertNotIn('id="jobs-active-count"', INDEX_HTML)
        self.assertIn('可用容量', INDEX_HTML)
        self.assertIn('Worker', INDEX_HTML)
        self.assertIn('任务', INDEX_HTML)

    def test_cancel_flow_has_cancelling_feedback(self) -> None:
        self.assertIn('正在取消', INDEX_HTML)
        self.assertIn('job.status === "cancelling"', INDEX_HTML)


class StaticUiCancellationGovernanceTests(unittest.TestCase):
    def read_static_html(self) -> str:
        return INDEX_HTML

    def test_worker_summary_uses_live_combined_fields(self) -> None:
        html = self.read_static_html()
        self.assertIn('summary.online_workers', html)
        self.assertIn('summary.busy_workers', html)
        self.assertIn('summary.queued_jobs', html)
        self.assertIn('summary.running_jobs', html)
        self.assertIn('summary.cancelling_jobs', html)
        self.assertIn('summary.effective_available_capacity', html)
        self.assertIn('id="worker-online-count"', html)
        self.assertIn('id="worker-loading-count"', html)
        self.assertIn('id="worker-busy-count"', html)
        self.assertIn('id="jobs-queued-count"', html)
        self.assertIn('id="jobs-generating-count"', html)
        self.assertIn('worker-card-metrics', html)
        self.assertIn('metric-item', html)
        self.assertNotIn('id="workers-capacity-available"', html)
        self.assertNotIn('id="worker-online-metric"', html)
        self.assertNotIn('id="jobs-active-count"', html)
        self.assertNotIn('workerRuntimeState(summary)', html)
        self.assertNotIn('id="workers-count-badge"', html)
        self.assertNotIn('id="jobs-count-badge"', html)
        self.assertNotIn('id="worker-runtime-state"', html)
        self.assertNotIn('summary.stuck_cancelling_workers', html)
        self.assertNotIn('summary.known_workers', html)
        self.assertNotIn('summary.total_workers', html)

    def test_cancelling_action_cell_delays_escalation_until_deadline(self) -> None:
        html = self.read_static_html()
        self.assertIn('DEFAULT_CANCEL_ESCALATION_DELAY_SECONDS = 10', html)
        self.assertIn('function cancellationEscalationReady(job)', html)
        self.assertIn('function formatCancellationCountdown(job)', html)
        self.assertIn('function cancellationDeadline(job)', html)
        self.assertIn('job.cancel_deadline_at', html)
        self.assertIn('job.cancel_requested_at', html)
        self.assertIn('cancel-spinner', html)
        self.assertIn('正在取消', html)
        self.assertIn('class="preview-btn force-cancel-btn"', html)
        self.assertIn('background: var(--error);', html)
        self.assertIn('class="cancel-detail"', html)
        self.assertIn('取消超时。可重试取消', html)
        self.assertIn('data-action="retry-cancel"', html)
        self.assertIn('取消失败，重试', html)
        self.assertNotIn('后可升级', html)
        self.assertNotIn('升级中', html)

    def test_history_panel_scrolls_inside_table_region(self) -> None:
        html = self.read_static_html()
        self.assertIn('class="panel history-panel"', html)
        self.assertIn('.history-panel {', html)
        self.assertIn('min-height: 420px;', html)
        self.assertIn('height: calc(100vh - 48px);', html)
        self.assertIn('overflow: hidden;', html)
        self.assertIn('.table-wrap {', html)
        self.assertIn('flex: 1 1 auto;', html)
        self.assertIn('min-height: 260px;', html)
        self.assertIn('overflow: auto;', html)
        self.assertIn('overscroll-behavior: contain;', html)

    def test_submit_panel_uses_compact_quality_select_and_modal(self) -> None:
        html = self.read_static_html()
        self.assertIn('class="prompt-header"', html)
        self.assertIn('Proposals', html)
        self.assertIn('id="quality-select"', html)
        self.assertIn('id="custom-quality-dialog"', html)
        self.assertIn('id="quality-summary"', html)
        self.assertIn('QUALITY_SUMMARIES', html)
        self.assertIn('let selectedQuality = "draft"', html)
        self.assertIn('<option value="custom">手动</option>', html)
        self.assertIn('class="row submit-row"', html)
        self.assertIn('<button id="submit-btn" type="button">提交任务</button>', html)
        self.assertIn('<button type="button" class="adv-toggle" id="adv-toggle">▸ 负向提示词</button>', html)
        self.assertLess(html.index('id="submit-btn"'), html.index('id="adv-toggle"'))
        self.assertLess(html.index('id="adv-toggle"'), html.index('id="adv-section"'))
        self.assertNotIn('手动设置</option>', html)
        self.assertNotIn('id="custom-params"', html)

    def test_active_polling_and_tick_include_cancelling(self) -> None:
        html = self.read_static_html()
        self.assertIn('const busy = hasActiveJobs(jobs);', html)
        self.assertIn('j.status === "queued" || j.status === "claimed" || j.status === "running" || j.status === "cancelling"', html)
        self.assertIn('job.status !== "running" && job.status !== "queued" && job.status !== "claimed" && job.status !== "cancelling"', html)
        self.assertIn('cells[6].innerHTML = actionCell(job);', html)


if __name__ == "__main__":
    unittest.main()
