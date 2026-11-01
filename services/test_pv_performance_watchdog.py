"""Delivery tests use synthetic reports and a fake sender; no network or devices."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services import pv_performance_watchdog as service
from pv_performance_io import atomic_json, read_json


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def report(active=True):
    incident = {"id": "example:pv1:2026-10-03", "opened": "2026-10-03",
                "evidence": {"score": .065, "days": 3, "threshold": .03}}
    event = {"kind": "inspection_opened", "target": "pv1", **incident}
    return {"model_id": "model", "summary": {"pv1": {"inspection": incident if active else None,
            "last_evidence_day": "2026-10-31"}}, "state": {"recent_events": [event] if active else []},
            "pattern": {"pattern": "relative_input_loss" if active else "no_open_inspection"},
            "monitoring_gaps": {"pv6": "Insufficient calibration"}, "quality": {}}


class WatchdogDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model_path = self.root / "model.json"
        atomic_json(self.model_path, {"model_id": "model"})
        self.args = service.parser().parse_args(["--model", str(self.model_path), "--logs", str(self.root / "logs"),
                                               "--runtime-dir", str(self.root / "runtime")])
        self.report = report()
        patcher = patch.object(service.monitor, "execute", side_effect=lambda *a: deepcopy(self.report))
        self.engine = patcher.start()
        self.addCleanup(patcher.stop)
        self.sender = Mock(return_value=True)

    def run_watchdog(self):
        return service.run(self.args, NOW, self.sender)

    def test_activation_summarizes_current_incidents_and_unchanged_runs_stay_quiet(self):
        self.assertEqual(self.run_watchdog()["messages_sent"], 1)
        self.assertIn("inspection recommended", self.sender.call_args.args[0])
        self.assertIn("Logged PV1: inspect", self.sender.call_args.args[1])
        self.assertEqual(self.run_watchdog()["messages_sent"], 0)
        self.assertEqual(self.sender.call_count, 1)
        saved = read_json(self.args.runtime_dir / "latest_report.json")
        self.assertTrue(saved["notifications_enabled"])
        self.assertEqual(saved["delivery"]["pending"], 0)

    def test_initial_catchup_does_not_email_resolved_historical_incidents(self):
        old = self.report["state"]["recent_events"][0]
        self.report = report(False)
        self.report["state"]["recent_events"] = [old, {**old, "kind": "inspection_recovered", "recovered": "2026-10-05"}]
        self.run_watchdog()
        self.assertNotIn("Logged PV1: inspect", self.sender.call_args.args[1])
        self.assertIn("No open inspection", self.sender.call_args.args[1])

    def test_failed_delivery_survives_restart_and_is_retried_without_requeuing(self):
        self.sender.return_value = False
        with self.assertRaises(RuntimeError):
            self.run_watchdog()
        path = self.args.runtime_dir / "notifications.json"
        self.assertEqual(len(read_json(path)["outbox"]), 1)
        self.assertEqual(read_json(self.args.runtime_dir / "latest_report.json")["delivery"]["pending"], 1)
        self.sender.return_value = True
        self.assertEqual(self.run_watchdog()["messages_sent"], 1)
        self.assertEqual(read_json(path)["outbox"], [])
        self.assertEqual(self.run_watchdog()["messages_sent"], 0)

    def test_sender_exception_keeps_the_durable_outbox(self):
        self.sender.side_effect = OSError("offline")
        with self.assertRaises(OSError):
            self.run_watchdog()
        self.assertEqual(len(read_json(self.args.runtime_dir / "notifications.json")["outbox"]), 1)

    def test_engine_journal_recovers_event_after_a_crash_between_scoring_and_delivery(self):
        self.report = report(False)
        self.run_watchdog()
        self.report = report()
        self.report["events"] = []  # No new engine transitions on the retry.
        self.assertEqual(self.run_watchdog()["messages_sent"], 1)
        self.assertIn("Logged PV1: inspect", self.sender.call_args.args[1])
        self.assertEqual(self.run_watchdog()["messages_sent"], 0)

    def test_recovery_and_coverage_changes_are_sent_once(self):
        self.run_watchdog()
        self.report["summary"]["pv1"]["inspection"] = None
        self.report["state"]["recent_events"].append({**self.report["state"]["recent_events"][0],
                                                      "kind": "inspection_recovered", "recovered": "2026-11-01"})
        self.assertEqual(self.run_watchdog()["messages_sent"], 1)
        self.assertIn("inspection closed", self.sender.call_args.args[1])
        self.report["quality"]["array_weather_error"] = "timeout"
        self.assertEqual(self.run_watchdog()["messages_sent"], 1)
        self.report["quality"]["array_weather_error"] = "another timeout"
        self.assertEqual(self.run_watchdog()["messages_sent"], 0)

    def test_dry_run_does_not_create_runtime_or_send(self):
        self.args.dry_run = True
        result = self.run_watchdog()
        self.assertFalse(result["notifications_enabled"])
        self.assertEqual(result["messages_pending"], 1)
        self.assertFalse(self.args.runtime_dir.exists())
        self.sender.assert_not_called()

    def test_rejects_input_model_overlap_and_model_change_before_running_engine(self):
        self.args.runtime_dir = self.args.logs
        with self.assertRaises(ValueError):
            self.run_watchdog()
        self.engine.assert_not_called()
        self.args.runtime_dir = self.root / "runtime"
        self.run_watchdog()
        atomic_json(self.model_path, {"model_id": "changed"})
        count = self.engine.call_count
        with self.assertRaises(ValueError):
            self.run_watchdog()
        self.assertEqual(self.engine.call_count, count)


if __name__ == "__main__":
    unittest.main()
