"""Service boundaries: synthetic data, fake weather, temporary state, no network."""

from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services import pv_accumulating_monitor as service
from services.test_pv_evidence import rows, model as evidence_model
from services.test_pv_performance_monitor import samples_for
from pv_evidence import identity
from pv_inspections import visually_resolve
from pv_performance import Policy, build_baseline, day_epoch
from pv_performance_io import atomic_json, read_json


def model():
    reference = {"version": 1, "end_exclusive": "2025-01-01", "site": asdict(Policy())}
    reference["model_id"] = identity(reference)
    relative = build_baseline([s for day in range(1, 7) for s in samples_for(f"2024-06-{day:02d}")],
                              "2024-06-01", "2025-01-01")
    array, pv1 = evidence_model(), evidence_model()
    array["reference_id"] = reference["model_id"]
    pv1["reference_id"] = identity({"reference": relative["model_id"], "target": "pv1"})
    for evidence in (array, pv1):
        evidence["model_id"] = identity(evidence)
    result = {"version": 1, "kind": "accumulating_array_inspection", "reference": reference,
              "evidence": array, "differential_reference": relative, "differential_evidence": {"pv1": pv1},
              "unavailable_targets": {"pv6": "Insufficient calibration"}, "limitations": []}
    result["model_id"] = identity(result)
    return result


def fake_weather(start, end, site):
    return ({epoch: {"ghi": 600., "diffuse": 100., "temperature": 20.}
             for epoch in range(day_epoch(start, site), day_epoch(end, site) + 86401, 3600)}, {"source": "test"})


def daily(start, end):
    return rows(start, [.1] * (date.fromisoformat(end) - date.fromisoformat(start)).days)


class AccumulatingServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model_path, self.state_path = self.root / "model.json", self.root / "state.json"
        atomic_json(self.model_path, model())
        patches = {
            "fetch_era5": fake_weather,
            "load_samples": lambda *a, **kw: ([], {"synthetic": True}),
            "daily_residuals": lambda ref, samples, weather, start, end: (daily(start, end), {}),
            "score_days": lambda predictor, samples, start, end: [{**r, "target": "pv1"} for r in daily(start, end)],
        }
        for name, function in patches.items():
            patcher = patch.object(service, name, side_effect=function)
            patcher.start()
            self.addCleanup(patcher.stop)

    def args(self, command="shadow", *extra):
        values = [command, "--model", str(self.model_path), "--logs", str(self.root / "logs")]
        if command == "shadow":
            values += ["--state", str(self.state_path)]
        return service.parser().parse_args(values + list(extra))

    def now(self, day=10):
        return datetime(2025, 7, day, 12, tzinfo=timezone.utc)

    def test_relative_runs_through_yesterday_array_is_delayed_and_rerun_is_idempotent(self):
        report = service.execute(self.args("shadow", "--from", "2025-07-01"), self.now())
        self.assertEqual(report["summary"]["array"]["last_processed_day"], "2025-07-03")
        self.assertEqual(report["summary"]["pv1"]["last_processed_day"], "2025-07-09")
        self.assertEqual(report["summary"]["array"]["evidence_age_days"], 7)
        self.assertEqual(len(report["events"]), 2)
        self.assertFalse(report["notifications_enabled"])
        again = service.execute(self.args(), self.now())
        self.assertFalse(again["events"])
        self.assertEqual(again["state"]["targets"], report["state"]["targets"])

    def test_weather_outage_preserves_array_cursor_and_keeps_relative_check_running(self):
        first = service.execute(self.args("shadow", "--from", "2025-07-01"), self.now())
        with patch.object(service, "fetch_era5", side_effect=OSError("offline")):
            report = service.execute(self.args(), self.now(11))
        self.assertEqual(report["state"]["targets"]["array"], first["state"]["targets"]["array"])
        self.assertEqual(report["summary"]["pv1"]["last_processed_day"], "2025-07-10")
        self.assertIn("offline", report["quality"]["array_weather_error"])
        recovered = service.execute(self.args(), self.now(12))
        self.assertEqual(recovered["summary"]["array"]["last_processed_day"], "2025-07-05")
        self.assertFalse(recovered["events"])

    def test_visual_resolution_ignores_array_backlog_and_reopens_from_new_days(self):
        service.execute(self.args("shadow", "--from", "2025-07-01"), self.now())
        state = read_json(self.state_path)
        visually_resolve(state, ["array", "pv1"], self.now(), "Checked; no visible fault")
        atomic_json(self.state_path, state)
        report = service.execute(self.args(), self.now(14))
        self.assertIsNone(report["summary"]["array"]["inspection"])
        self.assertEqual(report["summary"]["array"]["inspection_status"], "visually_resolved")
        self.assertEqual(report["summary"]["array"]["post_resolution_evidence_days"], 0)
        self.assertEqual(report["summary"]["pv1"]["inspection"]["opened"], "2025-07-13")
        report = service.execute(self.args(), self.now(20))
        self.assertEqual(report["summary"]["array"]["inspection"]["first_evidence"], "2025-07-11")
        self.assertEqual(report["summary"]["array"]["inspection"]["opened"], "2025-07-13")

    def test_incomplete_weather_waits_for_latest_day(self):
        site = Policy()
        weather, _ = fake_weather("2025-07-01", "2025-07-04", site)
        weather[day_epoch("2025-07-04", site)]["ghi"] = None
        self.assertEqual(service.last_complete_weather_end(weather, "2025-07-01", "2025-07-04", site),
                         "2025-07-03")

    def test_weather_day_completeness_handles_both_dst_transitions(self):
        site = Policy()
        for start, end in (("2025-03-30", "2025-03-31"), ("2025-10-26", "2025-10-27")):
            weather, _ = fake_weather(start, end, site)
            self.assertEqual(service.last_complete_weather_end(weather, start, end, site), end)
            weather.pop(day_epoch(end, site))
            self.assertEqual(service.last_complete_weather_end(weather, start, end, site), start)

    def test_no_weather_does_not_silently_consume_the_array_backlog(self):
        with patch.object(service, "fetch_era5", return_value=({}, {})):
            report = service.execute(self.args("shadow", "--from", "2025-07-01"), self.now())
        self.assertIsNone(report["summary"]["array"]["last_processed_day"])
        self.assertIn("array", report["monitoring_gaps"])
        self.assertIn("pv6", report["monitoring_gaps"])
        self.assertEqual(report["summary"]["pv1"]["last_processed_day"], "2025-07-09")
        # The explicit requested start must survive a failed first weather download.
        again = service.execute(self.args(), self.now(11))
        self.assertEqual(again["evaluation_start_by_target"]["array"], "2025-07-01")

    def test_replay_fails_visibly_on_weather_error_and_does_not_write_state(self):
        args = self.args("replay", "--from", "2025-07-01", "--until", "2025-07-05")
        with patch.object(service, "fetch_era5", side_effect=OSError("offline")), self.assertRaises(OSError):
            service.execute(args, self.now())
        self.assertFalse(self.state_path.exists())

    def test_output_cannot_overwrite_frozen_model_or_inputs(self):
        for destination in (self.model_path, self.root / "logs" / "report.json", self.state_path):
            with self.assertRaises(ValueError):
                service.execute(self.args("shadow", "--output", str(destination)), self.now())

    def test_model_and_state_mismatch_fail_before_advancing(self):
        service.execute(self.args("shadow", "--from", "2025-07-01"), self.now())
        state = read_json(self.state_path)
        state["model_id"] = "another-model"
        atomic_json(self.state_path, state)
        with self.assertRaises(ValueError):
            service.execute(self.args(), self.now(11))
        self.assertEqual(read_json(self.state_path), state)

    def test_persisted_days_cannot_be_rewritten_or_skipped(self):
        service.execute(self.args("shadow", "--from", "2025-07-01"), self.now())
        with self.assertRaises(ValueError):
            service.execute(self.args("shadow", "--from", "2025-07-01"), self.now(11))

    def test_calibration_refuses_overlapping_periods_or_replacing_a_model(self):
        values = ["calibrate", "--history-exports", str(self.root / "exports"),
                  "--reference-from", "2024-01-01", "--reference-until", "2025-01-01",
                  "--from", "2025-01-01", "--until", "2025-07-01", "--output", str(self.model_path)]
        args = service.parser().parse_args(values)
        original = self.model_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "destination exists"):
            service.execute(args, self.now())
        self.assertEqual(original, self.model_path.read_bytes())
        args.output = self.root / "another.json"
        args.reference_until = "2025-03-01"
        with self.assertRaisesRegex(ValueError, "separate completed"):
            service.execute(args, self.now())
        self.assertFalse(args.output.exists())

    def test_replay_requires_nonempty_completed_interval_and_explicit_valid_simulation(self):
        for extra in (("--from", "2025-07-04", "--until", "2025-07-04"),
                      ("--from", "2025-07-04", "--until", "2025-07-11"),
                      ("--from", "2025-07-01", "--until", "2025-07-05", "--simulate-loss", "pv6:0.1")):
            with self.assertRaises(ValueError):
                service.execute(self.args("replay", *extra), self.now())


if __name__ == "__main__":
    unittest.main()
