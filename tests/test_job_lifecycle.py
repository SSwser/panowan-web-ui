import unittest

from app.jobs.lifecycle import (
    INFLIGHT_STATES,
    JOB_STATE_CANCELLED,
    JOB_STATE_FAILED,
    JOB_STATE_SUCCEEDED,
    TERMINAL_STATES,
    IllegalTransitionError,
    apply_transition,
    can_transition,
    is_terminal,
    normalize_legacy_record,
    normalize_restored_inflight_record,
)


class CanonicalTransitionTests(unittest.TestCase):
    def test_queued_can_become_claimed_or_cancelled(self):
        self.assertTrue(can_transition("queued", "claimed"))
        self.assertTrue(can_transition("queued", "cancelled"))

    def test_claimed_can_become_running_cancelling_or_failed(self):
        self.assertTrue(can_transition("claimed", "running"))
        self.assertTrue(can_transition("claimed", "cancelling"))
        self.assertTrue(can_transition("claimed", "failed"))

    def test_allows_running_to_cancelling(self):
        self.assertTrue(can_transition("running", "cancelling"))

    def test_running_can_terminate_in_succeeded_or_failed(self):
        self.assertTrue(can_transition("running", "succeeded"))
        self.assertTrue(can_transition("running", "failed"))

    def test_cancelling_can_terminate_in_cancelled_or_failed(self):
        self.assertTrue(can_transition("cancelling", "cancelled"))
        self.assertTrue(can_transition("cancelling", "failed"))
        self.assertFalse(can_transition("cancelling", "succeeded"))
        self.assertFalse(can_transition("cancelling", "running"))

    def test_rejects_transition_out_of_terminal_state(self):
        self.assertFalse(can_transition("succeeded", "running"))
        self.assertFalse(can_transition("failed", "queued"))
        self.assertFalse(can_transition("cancelled", "claimed"))

    def test_rejects_running_to_queued(self):
        self.assertFalse(can_transition("running", "queued"))

    def test_terminal_states_set_matches_adr(self):
        self.assertEqual(
            TERMINAL_STATES,
            frozenset({JOB_STATE_SUCCEEDED, JOB_STATE_FAILED, JOB_STATE_CANCELLED}),
        )

    def test_is_terminal(self):
        self.assertTrue(is_terminal("succeeded"))
        self.assertTrue(is_terminal("failed"))
        self.assertTrue(is_terminal("cancelled"))
        self.assertFalse(is_terminal("running"))


class ApplyTransitionTests(unittest.TestCase):
    def test_apply_transition_returns_copy_with_new_status(self):
        record = {"job_id": "j1", "status": "queued"}
        updated = apply_transition(record, "claimed")
        self.assertEqual(updated["status"], "claimed")
        self.assertEqual(record["status"], "queued")

    def test_apply_transition_rejects_illegal_change(self):
        record = {"job_id": "j1", "status": "succeeded"}
        with self.assertRaises(IllegalTransitionError):
            apply_transition(record, "queued")


class NormalizationTests(unittest.TestCase):
    def test_normalizes_legacy_completed_to_succeeded(self):
        record = normalize_legacy_record({"status": "completed", "error": None})
        self.assertEqual(record["status"], "succeeded")

    def test_normalizes_legacy_cancelled_failure_to_cancelled(self):
        record = normalize_legacy_record(
            {"status": "failed", "error": "Cancelled by user"}
        )
        self.assertEqual(record["status"], "cancelled")
        self.assertIsNone(record["error"])

    def test_normalize_legacy_record_does_not_mutate_input(self):
        original = {"status": "completed", "error": None}
        normalize_legacy_record(original)
        self.assertEqual(original["status"], "completed")

    def test_real_failure_is_preserved(self):
        record = normalize_legacy_record(
            {"status": "failed", "error": "engine exploded"}
        )
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"], "engine exploded")

    def test_canonical_states_pass_through_normalization(self):
        for state in ("queued", "claimed", "running", "succeeded", "cancelled"):
            record = normalize_legacy_record({"status": state, "error": None})
            self.assertEqual(record["status"], state)


class RestoreNormalizationTests(unittest.TestCase):
    def test_restore_marks_inflight_as_failed(self):
        for state in INFLIGHT_STATES:
            record = normalize_restored_inflight_record(
                {"status": state, "finished_at": None, "error": None},
                "2026-05-01T00:00:00+00:00",
            )
            self.assertEqual(record["status"], "failed")
            self.assertEqual(
                record["error"], "Service restarted before the job completed"
            )
            self.assertEqual(record["finished_at"], "2026-05-01T00:00:00+00:00")

    def test_restore_preserves_existing_finished_at(self):
        record = normalize_restored_inflight_record(
            {"status": "running", "finished_at": "earlier", "error": None},
            "now",
        )
        self.assertEqual(record["finished_at"], "earlier")

    def test_restore_normalizes_legacy_completed_first(self):
        record = normalize_restored_inflight_record(
            {"status": "completed", "finished_at": "later", "error": None},
            "now",
        )
        self.assertEqual(record["status"], "succeeded")

    def test_restore_preserves_terminal_failed(self):
        record = normalize_restored_inflight_record(
            {"status": "failed", "finished_at": "earlier", "error": "boom"},
            "now",
        )
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"], "boom")


if __name__ == "__main__":
    unittest.main()
