"""Synthetic checks for sensitive, calibrated multi-day inspection evidence."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))
from pv_evidence import EvidencePolicy, advance, calibrate, new_state
from pv_accumulating import describe_pattern


def rows(start, values):
    day = date.fromisoformat(start)
    return [{"day": (day + timedelta(days=i)).isoformat(), "qualified": value is not None,
             **({"deficit": value} if value is not None else {})} for i, value in enumerate(values)]


def model(bias=0.):
    return calibrate(rows("2025-01-01", [bias + (-.01 if i % 2 else .01) for i in range(60)]),
                     "2025-01-01", "2025-04-01", "reference")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.model = model()

    def test_small_loss_accumulates_before_any_old_daily_threshold_is_met(self):
        state = new_state(self.model)
        scored, events = advance(state, rows("2025-04-01", [.08] * 5), self.model)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["opened"], "2025-04-03")
        self.assertEqual(events[0]["evidence"]["days"], 3)
        self.assertTrue(scored[-1]["inspection_open"])

    def test_one_shutdown_day_cannot_dominate_otherwise_normal_days(self):
        for values in ([1, 0, 0, 0, 0], [0, 0, 1, .01, .01]):
            _, events = advance(new_state(self.model), rows("2025-04-01", values), self.model)
            self.assertFalse(events)

    def test_normal_noise_and_subminimum_loss_do_not_open(self):
        for values in ([.01, -.01] * 10, [.02] * 12):
            _, events = advance(new_state(self.model), rows("2025-04-01", values), self.model)
            self.assertFalse(events)

    def test_calibration_removes_reference_bias_without_adapting_to_new_loss(self):
        calibrated = model(.08)
        before = deepcopy(calibrated)
        _, quiet = advance(new_state(calibrated), rows("2025-04-01", [.08] * 5), calibrated)
        _, changed = advance(new_state(calibrated), rows("2025-04-01", [.16] * 5), calibrated)
        self.assertFalse(quiet)
        self.assertTrue(changed)
        self.assertEqual(calibrated, before)

    def test_missing_days_pause_evidence_and_do_not_recover(self):
        state = new_state(self.model)
        _, events = advance(state, rows("2025-04-01", [.08, None, .08, None, .08] + [None] * 30), self.model)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["opened"], "2025-04-05")
        self.assertIsNotNone(state["incident"])
        self.assertEqual(state["latest"]["status"], "insufficient_evidence")

    def test_long_gap_cannot_join_old_and_new_evidence(self):
        state = new_state(self.model)
        advance(state, rows("2025-04-01", [.08, .08]), self.model)
        _, events = advance(state, rows("2025-05-01", [.08]), self.model)
        self.assertFalse(events)

    def test_recovery_requires_three_good_days_and_one_incident_is_not_reopened_daily(self):
        state = new_state(self.model)
        _, events = advance(state, rows("2025-04-01", [.08] * 8 + [0, None, 0, 0]), self.model)
        self.assertEqual([e["kind"] for e in events], ["inspection_opened", "inspection_recovered"])
        self.assertEqual(events[-1]["recovered"], "2025-04-12")
        self.assertIsNone(state["incident"])

    def test_streaming_matches_replay_and_duplicate_closed_days_are_idempotent(self):
        daily = rows("2025-04-01", [.08] * 8 + [0] * 4)
        full, stream = new_state(self.model), new_state(self.model)
        _, expected = advance(full, daily, self.model)
        events = []
        for item in daily:
            _, extra = advance(stream, [item], self.model)
            events.extend(extra)
        self.assertEqual(full, stream)
        self.assertEqual(events, expected)
        before = deepcopy(stream)
        self.assertEqual(advance(stream, daily, self.model), ([], []))
        self.assertEqual(stream, before)

    def test_calibration_cannot_include_evaluation_days_or_be_silently_changed(self):
        with self.assertRaises(ValueError):
            calibrate(rows("2025-06-01", [.1] * 60), "2025-01-01", "2025-07-01", "reference")
        with self.assertRaises(ValueError):
            advance(new_state(self.model), rows("2025-03-31", [.1]), self.model)
        changed = deepcopy(self.model)
        changed["thresholds"]["3"] = .001
        with self.assertRaises(ValueError):
            advance(new_state(self.model), [], changed)
        wrong_state = new_state(self.model)
        wrong_state["model_id"] = "another-model"
        with self.assertRaises(ValueError):
            advance(wrong_state, [], self.model)

    def test_missing_calibration_support_and_invalid_measurements_fail_visibly(self):
        with self.assertRaises(ValueError):
            calibrate(rows("2025-01-01", [0] * 10), "2025-01-01", "2025-04-01", "reference")
        for invalid in (float("nan"), float("inf"), True, 1.1):
            with self.assertRaises(ValueError):
                advance(new_state(self.model), rows("2025-04-01", [invalid]), self.model)
        with self.assertRaises(ValueError):
            advance(new_state(self.model), rows("2025-04-01", [.1]) * 2, self.model)

    def test_pattern_separates_shared_and_relative_loss_without_claiming_cause(self):
        self.assertEqual(describe_pattern({"array": {"incident": {"id": "a"}}})["pattern"],
                         "whole_array_loss_without_detected_relative_imbalance")
        mixed = describe_pattern({"array": {"incident": {"id": "a"}}, "pv2": {"incident": {"id": "b"}}})
        self.assertEqual(mixed["pattern"], "whole_array_loss_with_relative_imbalance")
        self.assertFalse(mixed["cause_confirmed"])
        self.assertIsNone(mixed["physical_string_mapping"])


if __name__ == "__main__":
    unittest.main()
