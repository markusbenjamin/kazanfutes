"""Visual resolutions: synthetic evidence and temporary files; no actual inspection claims."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services import pv_performance_watchdog as watchdog
from services.test_pv_evidence import model, rows
from services.test_pv_accumulating_monitor import model as combined_model
from pv_accumulating import evidence_models, describe_pattern
from pv_evidence import advance, new_state
from pv_inspections import evidence_after_inspection, inspection_details, visually_resolve
from pv_performance_io import atomic_json, read_json


def april(day):
    return datetime(2025, 4, day, 12, tzinfo=timezone.utc)


class VisualEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.model = model()
        self.state = {"version": 1, "model_id": "combined", "targets": {t: new_state(self.model) for t in ("array", "pv1", "pv2")}}
        for state in self.state["targets"].values():
            advance(state, rows("2025-04-01", [.08] * 3), self.model)

    def test_resolution_is_targeted_audited_and_does_not_claim_measured_recovery(self):
        before = deepcopy(self.state)
        events = visually_resolve(self.state, ["pv1"], april(4), "Checked glass and visible shading", "Beno")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "inspection_visually_resolved")
        item = self.state["targets"]["pv1"]
        self.assertIsNone(item["incident"])
        self.assertEqual(item["last_day"], before["targets"]["pv1"]["last_day"])
        self.assertEqual(self.state["targets"]["pv2"], before["targets"]["pv2"])
        self.assertEqual(self.state["targets"]["array"], before["targets"]["array"])
        audit = self.state["visual_resolutions"][0]
        self.assertEqual(audit["previous_evidence"], before["targets"]["pv1"]["history"])
        self.assertEqual(audit["previous_incident"], before["targets"]["pv1"]["incident"])
        self.assertFalse(audit["performance_recovery_confirmed"])
        self.assertEqual(inspection_details(item)["inspection_status"], "visually_resolved")
        self.assertEqual(inspection_details(item)["post_resolution_evidence_days"], 0)

    def test_delayed_array_days_through_inspection_day_cannot_reopen_but_fresh_loss_does(self):
        visually_resolve(self.state, ["array"], april(10), "No visible fault")
        state = self.state["targets"]["array"]
        delayed = evidence_after_inspection(rows("2025-04-04", [.2] * 7), state)
        self.assertTrue(all(not r["qualified"] for r in delayed))
        self.assertFalse(advance(state, delayed, self.model)[1])
        self.assertFalse(advance(state, evidence_after_inspection(rows("2025-04-11", [.08] * 2), state), self.model)[1])
        events = advance(state, evidence_after_inspection(rows("2025-04-13", [.08]), state), self.model)[1]
        self.assertEqual(events[0]["opened"], "2025-04-13")
        self.assertEqual(events[0]["first_evidence"], "2025-04-11")
        self.assertEqual(inspection_details(state)["inspection_status"], "open")
        self.assertEqual(len(self.state["visual_resolutions"]), 1)

    def test_repeating_resolution_without_open_incident_preserves_new_evidence(self):
        visually_resolve(self.state, ["pv1"], april(4), "No visible fault")
        state = self.state["targets"]["pv1"]
        advance(state, evidence_after_inspection(rows("2025-04-04", [.08] * 3), state), self.model)
        before = deepcopy(self.state)
        self.assertFalse(visually_resolve(self.state, ["pv1"], april(7), "Repeat click"))
        self.assertEqual(self.state, before)
        self.assertTrue(advance(state, rows("2025-04-07", [.08]), self.model)[1])

    def test_missing_and_good_post_inspection_days_do_not_create_recovery_claims(self):
        visually_resolve(self.state, ["pv1"], april(4), "No visible fault")
        state = self.state["targets"]["pv1"]
        scored, events = advance(state, evidence_after_inspection(rows("2025-04-04", [None, 0, None, 0, 0]), state), self.model)
        self.assertFalse(events)
        self.assertIsNone(state["incident"])
        self.assertFalse(state["visual_resolution"]["performance_recovery_confirmed"])

    def test_invalid_actions_fail_before_any_state_changes(self):
        for targets, now, note, inspector in (([], april(4), "OK", "admin"),
                (["pv1", "unknown"], april(4), "OK", "admin"), (["pv1", "pv1"], april(4), "OK", "admin"),
                (["pv1"], april(4), "  ", "admin"), (["pv1"], april(4), "OK", ""),
                (["pv1"], april(3), "OK", "admin"), (["pv1"], datetime(2025, 4, 4), "OK", "admin")):
            before = deepcopy(self.state)
            with self.assertRaises(ValueError):
                visually_resolve(self.state, targets, now, note, inspector)
            self.assertEqual(self.state, before)

    def test_unresolved_targets_keep_the_original_detection_path(self):
        values = rows("2025-04-04", [.08] * 5)
        self.assertIs(evidence_after_inspection(values, self.state["targets"]["pv2"]), values)


class VisualCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / "runtime"
        self.model_path = self.root / "model.json"
        self.model = combined_model()
        atomic_json(self.model_path, self.model)
        self.now = datetime(2025, 7, 4, 12, tzinfo=timezone.utc)
        state = {"version": 1, "model_id": self.model["model_id"], "last_run": "2025-07-04T07:15:00+02:00",
                 "targets": {t: new_state(e) for t, e in evidence_models(self.model).items()}, "recent_events": []}
        for target, evidence in evidence_models(self.model).items():
            _, changes = advance(state["targets"][target], rows("2025-07-01", [.1] * 3), evidence)
            state["recent_events"] += [{**event, "target": target} for event in changes]
        summary = {t: {"inspection": s["incident"], "last_evidence_day": s["last_evidence_day"],
                       **inspection_details(s)} for t, s in state["targets"].items()}
        report = {"model_id": self.model["model_id"], "state": state, "summary": summary,
                  "pattern": describe_pattern(state["targets"]), "quality": {}, "monitoring_gaps": {}, "events": []}
        atomic_json(self.runtime / "evidence_state.json", state)
        atomic_json(self.runtime / "latest_report.json", report)
        self.sender = Mock(return_value=True)
        watchdog.publish_report(self.args("check"), self.runtime, report, None, self.now, self.sender)
        self.sender.reset_mock()

    def args(self, command, *extra):
        return watchdog.parser().parse_args([command, "--model", str(self.model_path),
            "--logs", str(self.root / "logs"), "--runtime-dir", str(self.runtime), *extra])

    def resolve(self, *extra):
        return watchdog.run(self.args("resolve", "--target", "pv1", "--note", "No visible damage or shade", *extra), self.now, self.sender)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.runtime.glob("*.json")}

    def test_command_closes_selected_target_emails_a_distinct_result_and_repeat_stays_quiet(self):
        result = self.resolve()
        self.assertEqual(result["visually_resolved_targets"], ["pv1"])
        self.assertEqual(result["summary"]["pv1"]["inspection_status"], "visually_resolved")
        self.assertIsNotNone(result["summary"]["array"]["inspection"])
        self.assertIn("Visual inspection recorded", self.sender.call_args.args[0])
        self.assertIn("Production recovery remains unconfirmed", self.sender.call_args.args[1])
        again = self.resolve()
        self.assertEqual(again["messages_sent"], 0)
        self.assertEqual(again["visually_resolved_targets"], [])
        self.assertEqual(self.sender.call_count, 1)

    def test_all_and_status_and_dry_run_preserve_canonical_audit(self):
        before = self.snapshot()
        result = self.resolve("--dry-run")
        self.assertEqual(result["visually_resolved_targets"], ["pv1"])
        self.assertEqual(self.snapshot(), before)
        self.sender.assert_not_called()
        result = watchdog.run(self.args("resolve", "--target", "all", "--note", "Checked entire array"), self.now, self.sender)
        self.assertEqual(set(result["visually_resolved_targets"]), {"array", "pv1"})
        before = self.snapshot()
        status = watchdog.run(self.args("status"), self.now, self.sender)
        self.assertEqual(len(status["visual_resolutions"]), 2)
        self.assertEqual(status["last_measurement_check"], "2025-07-04T07:15:00+02:00")
        self.assertEqual(self.snapshot(), before)

    def test_delivery_failure_keeps_resolution_and_retries_once(self):
        self.sender.return_value = False
        with self.assertRaises(RuntimeError):
            self.resolve()
        state = read_json(self.runtime / "evidence_state.json")
        self.assertIsNone(state["targets"]["pv1"]["incident"])
        self.assertEqual(len(read_json(self.runtime / "notifications.json")["outbox"]), 1)
        self.sender.return_value = True
        self.assertEqual(self.resolve()["messages_sent"], 1)
        self.assertEqual(self.resolve()["messages_sent"], 0)

    def test_first_notification_includes_the_manual_resolution_if_delivery_was_not_initialized(self):
        (self.runtime / "notifications.json").unlink()
        self.resolve()
        self.assertIn("visually resolved", self.sender.call_args.args[1])
        self.assertIn("visually checked on 2025-07-04", self.sender.call_args.args[1])

    def test_scheduled_run_recovers_resolution_after_crash_before_notification_queue(self):
        with patch.object(watchdog, "publish_report", side_effect=RuntimeError("process stopped")), self.assertRaises(RuntimeError):
            self.resolve()
        state = read_json(self.runtime / "evidence_state.json")
        stale_report = read_json(self.runtime / "latest_report.json")
        current = watchdog.refresh_inspection_report(stale_report, state)
        with patch.object(watchdog.monitor, "execute", return_value=current):
            result = watchdog.run(self.args("check"), self.now, self.sender)
        self.assertEqual(result["messages_sent"], 1)
        self.assertIn("visually resolved", self.sender.call_args.args[1])

    def test_invalid_scope_missing_note_and_model_mismatch_never_change_state(self):
        for extra in (("--target", "pv8", "--note", "OK"), ("--target", "all", "--target", "pv1", "--note", "OK"),
                      ("--target", "pv1"), ("--target", "pv1", "--target", "pv1", "--note", "OK")):
            before = self.snapshot()
            with self.assertRaises(ValueError):
                watchdog.run(self.args("resolve", *extra), self.now, self.sender)
            self.assertEqual(self.snapshot(), before)
        state = read_json(self.runtime / "evidence_state.json")
        state["model_id"] = "wrong"
        atomic_json(self.runtime / "evidence_state.json", state)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.resolve()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
