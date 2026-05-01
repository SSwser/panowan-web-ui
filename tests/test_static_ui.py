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


if __name__ == "__main__":
    unittest.main()
