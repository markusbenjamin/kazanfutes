"""PV performance tests use synthetic observations and temporary files only."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from services import pv_performance_monitor as service
from pv_performance import (
    Policy, Predictor, Sample, TARGETS, advance, build_baseline, day_epoch,
    new_state, score_days, solar_position,
)
from pv_performance_io import atomic_json, load_samples, parse_timestamp, read_json, state_lock


POLICY = Policy()
ZONE = ZoneInfo(POLICY.timezone)
NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def samples_for(day, *, loss=0, channel=1, weather=True, angle_shift=0):
    samples = []
    for minute in range(0, 125, 5):
        currents = [8., 8., 8., 8., 0., 8., 0., 8.]
        voltages = [500., 500., 500., 500., 200., 200., 200., 200.]
        currents[channel - 1] *= 1 - loss
        dc = sum(i * v / 1000 for i, v in zip(currents, voltages))
        epoch = day_epoch(day, POLICY) + (10 * 60 + minute) * 60
        samples.append(Sample(epoch, day, 180 + minute * .01 + angle_shift, 40, 10 + minute / 60,
                              tuple(currents), tuple(voltages), dc * .98, dc,
                              50000 if weather else None, 20 if weather else None))
    return samples


def baseline():
    rows = [s for day in range(1, 7) for s in samples_for(f"2026-06-{day:02d}")]
    return build_baseline(rows, "2026-06-01", "2026-06-07")


def raw_sample(sample, received_delay=10):
    row = {"timestamp": datetime.fromtimestamp(sample.epoch + received_delay, ZONE).strftime("%Y-%m-%d-%H-%M-%S"),
           "source_timestamp": datetime.fromtimestamp(sample.epoch, ZONE).isoformat(),
           "active_power_kw": sample.ac_kw, "total_input_power_kw": sample.dc_kw}
    for channel in range(1, 9):
        row[f"pv{channel}_input_current_a"] = sample.currents[channel - 1]
        row[f"pv{channel}_input_voltage_v"] = sample.voltages[channel - 1]
    return row


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class PredictionTests(unittest.TestCase):
    def setUp(self):
        self.model = baseline()
        self.predictor = Predictor(self.model)

    def test_persistent_loss_opens_after_three_days_and_two_days_recover(self):
        samples = [s for day in range(8, 13) for s in samples_for(f"2026-06-{day:02d}", loss=.25 if day < 11 else 0)]
        daily = score_days(self.predictor, samples, "2026-06-08", "2026-06-13")
        state = new_state(self.model["model_id"])
        events = advance(state, daily, self.predictor)
        pv1 = [event for event in events if event["target"] == "pv1"]
        self.assertEqual([event["kind"] for event in pv1], ["candidate_opened", "candidate_recovered"])
        self.assertEqual(pv1[0]["opened"], "2026-06-10")
        self.assertEqual(pv1[1]["recovered"], "2026-06-12")
        self.assertAlmostEqual(pv1[0]["evidence"]["deficit"], .25)
        self.assertEqual(pv1[0]["evidence"]["signature"], "current")
        self.assertFalse(advance(json.loads(json.dumps(state)), daily, self.predictor))

    def test_zero_target_is_detected_not_filtered_out(self):
        daily = score_days(self.predictor, samples_for("2026-06-08", loss=1), "2026-06-08", "2026-06-09")
        row = next(row for row in daily if row["target"] == "pv1")
        self.assertTrue(row["qualified"])
        self.assertEqual(row["deficit"], 1)

    def test_independent_weather_can_detect_common_loss(self):
        samples = [replace(s, ac_kw=s.ac_kw * .6) for s in samples_for("2026-06-08")]
        row = next(r for r in score_days(self.predictor, samples, "2026-06-08", "2026-06-09") if r["target"] == "array")
        self.assertTrue(row["qualified"])
        self.assertAlmostEqual(row["deficit"], .4)
        self.assertEqual(row["signature"], "weather_relative_array_output")

    def test_voltage_loss_is_distinguished_from_current_loss(self):
        samples = []
        for sample in samples_for("2026-06-08"):
            voltages = list(sample.voltages)
            voltages[0] *= .7
            samples.append(replace(sample, voltages=tuple(voltages)))
        row = next(r for r in score_days(self.predictor, samples, "2026-06-08", "2026-06-09") if r["target"] == "pv1")
        self.assertEqual(row["signature"], "voltage")
        self.assertAlmostEqual(row["deficit"], .3)

    def test_unseen_sun_geometry_abstains(self):
        daily = score_days(self.predictor, samples_for("2026-06-08", angle_shift=25), "2026-06-08", "2026-06-09")
        self.assertFalse(any(r["qualified"] for r in daily))
        self.assertIn("insufficient_comparable_history", daily[0]["exclusions"])

    def test_reference_samples_from_one_day_do_not_imply_independent_support(self):
        model = build_baseline(samples_for("2026-06-01"), "2026-06-01", "2026-06-02")
        daily = score_days(Predictor(model), samples_for("2026-06-08"), "2026-06-08", "2026-06-09")
        self.assertFalse(any(r["qualified"] for r in daily))

    def test_clipping_weather_absence_and_missing_target_are_explicit(self):
        for change, target, expected in (({"ac_kw": 30.}, "pv1", "clipping"),
                                         ({"lux": None}, "array", "missing_or_dim_weather"),
                                         ({"currents": (None,) + (8.,) * 7}, "pv1", "missing_target")):
            samples = [replace(s, **change) for s in samples_for("2026-06-08")]
            daily = score_days(self.predictor, samples, "2026-06-08", "2026-06-09")
            row = next(r for r in daily if r["target"] == target)
            self.assertFalse(row["qualified"])
            self.assertIn(expected, row["exclusions"])

    def test_unstable_or_gapped_peer_is_not_a_reference(self):
        samples = samples_for("2026-06-08")
        unstable = []
        for index, sample in enumerate(samples):
            currents = list(sample.currents)
            currents[3] = 4 if index % 2 else 8
            unstable.append(replace(sample, currents=tuple(currents)))
        for observations, reason in ((unstable, "unstable_reference"), (samples[::2], "reference_gap")):
            row = score_days(self.predictor, observations, "2026-06-08", "2026-06-09")[0]
            self.assertFalse(row["qualified"])
            self.assertIn(reason, row["exclusions"])

    def test_no_future_baseline_evaluation_and_baseline_never_adapts(self):
        before = json.dumps(self.model, sort_keys=True)
        with self.assertRaises(ValueError):
            score_days(self.predictor, samples_for("2026-06-02"), "2026-06-02", "2026-06-03")
        score_days(self.predictor, samples_for("2026-06-08", loss=.3), "2026-06-08", "2026-06-09")
        self.assertEqual(before, json.dumps(self.model, sort_keys=True))
        changed = deepcopy(self.model)
        changed["policy"]["main_loss_threshold"] = .5
        with self.assertRaises(ValueError):
            Predictor(changed)

    def test_simulations_are_explicit_and_do_not_change_input_observations(self):
        samples = samples_for("2026-06-08")
        before = list(samples)
        row = score_days(self.predictor, samples, "2026-06-08", "2026-06-09", simulation={"pv1": .2})[0]
        self.assertAlmostEqual(row["deficit"], .2)
        self.assertEqual(samples, before)
        with self.assertRaises(ValueError):
            score_days(self.predictor, samples, "2026-06-08", "2026-06-09", simulation={"pv1": float("nan")})

    def test_missing_days_cannot_resolve_an_incident(self):
        samples = [s for day in range(8, 11) for s in samples_for(f"2026-06-{day:02d}", loss=.3)]
        state = new_state(self.model["model_id"])
        daily = score_days(self.predictor, samples, "2026-06-08", "2026-06-30")
        events = advance(state, daily, self.predictor)
        self.assertEqual(len([e for e in events if e["target"] == "pv1"]), 1)
        self.assertIsNotNone(state["targets"]["pv1"]["incident"])
        self.assertEqual(state["targets"]["pv1"]["latest"]["status"], "insufficient_evidence")

    def test_evidence_cannot_accumulate_across_a_long_gap(self):
        samples = [s for day in ("2026-06-08", "2026-06-09", "2026-07-01") for s in samples_for(day, loss=.3)]
        state = new_state(self.model["model_id"])
        events = advance(state, score_days(self.predictor, samples, "2026-06-08", "2026-07-02"), self.predictor)
        self.assertFalse([e for e in events if e["target"] == "pv1"])

    def test_state_model_mismatch_and_partial_day_records_fail(self):
        with self.assertRaises(ValueError):
            advance(new_state("another-model"), [], self.predictor)
        daily = score_days(self.predictor, samples_for("2026-06-08"), "2026-06-08", "2026-06-09")
        with self.assertRaises(ValueError):
            advance(new_state(self.model["model_id"]), daily[:-1], self.predictor)


class InputTests(unittest.TestCase):
    def test_history_registers_match_the_independent_logger_overlap(self):
        from pv_history_export import decode_record
        words = [1773828000, 6488549, 462815240, 467213206, 161291225, 144509341,
                 25561245, 40764010, 405, 83, 411, 155388235, 1408239938, 1408368640,
                 1407909888, 1048576, 1003094016, 328073216, 556138826, 33568293,
                 246349873, 4051766969, 4294901760, 4294934527, 4294934527, 4294934527,
                 4294934527, 4294934527, 32767, 0]
        sample = decode_record(words, POLICY)
        self.assertEqual(sample.currents, (3.9, 6.18, 6.22, 4.05, 0., .83, 0., 4.11))
        self.assertEqual(sample.voltages, (706.2, 706.2, 712.9, 712.9, 246.1, 246.1, 220.5, 220.5))
        self.assertEqual(sample.ac_kw, 15.306)
        self.assertIsNone(sample.dc_kw)
        self.assertEqual(sample.epoch, parse_timestamp("2026-03-18T10:00:00+01:00", POLICY))

    def test_export_acquisition_after_baseline_boundary_is_rejected(self):
        from pv_history_export import load_history_exports
        with tempfile.TemporaryDirectory() as directory:
            # Exclusion must happen before parsing; this is deliberately not a valid export.
            Path(directory, "his_inv_extraction_20260121122256072.csv").write_text("future export")
            with self.assertRaisesRegex(ValueError, "No history exports available"):
                load_history_exports(directory, "2025-01-01", "2026-01-01", POLICY)

    def test_local_timestamp_and_both_dst_offsets(self):
        self.assertEqual(parse_timestamp("2026-06-01-12-00-00", POLICY), parse_timestamp("2026-06-01T10:00:00Z", POLICY))
        self.assertIsNone(parse_timestamp("2026-10-25-02-30-00", POLICY))
        self.assertIsNone(parse_timestamp("2026-03-29-02-30-00", POLICY))
        early = parse_timestamp("2026-10-25T02:30:00+02:00", POLICY)
        late = parse_timestamp("2026-10-25T02:30:00+01:00", POLICY)
        self.assertEqual(late - early, 3600)
        self.assertEqual(day_epoch("2026-03-30", POLICY) - day_epoch("2026-03-29", POLICY), 23 * 3600)

    def test_solar_geometry_is_time_zone_independent_and_physically_plausible(self):
        noon = parse_timestamp("2026-06-21T10:45:00Z", POLICY)
        az, elevation, hour = solar_position(noon, POLICY)
        self.assertTrue(175 < az < 185)
        self.assertTrue(64 < elevation < 67)
        self.assertAlmostEqual(hour, 12, delta=.1)
        self.assertLess(solar_position(noon - 12 * 3600, POLICY)[1], 0)

    def test_stale_future_and_duplicate_source_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = samples_for("2026-06-08")[0]
            first = raw_sample(sample)
            revision = raw_sample(replace(sample, ac_kw=1), received_delay=30)
            stale = raw_sample(replace(sample, epoch=sample.epoch + 300), received_delay=1800)
            future = raw_sample(replace(sample, epoch=sample.epoch + 600), received_delay=-120)
            write_rows(root / "electricity/pv_inverter.json", [revision, stale, future, first, first])
            observations, quality = load_samples(root, "2026-06-08", "2026-06-09", POLICY)
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0].ac_kw, first["active_power_kw"])
            self.assertEqual(quality["pv_invalid_or_stale_source"], 2)
            self.assertEqual(quality["pv_duplicate_buckets"], 2)

    def test_legacy_opt_in_and_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = raw_sample(samples_for("2026-06-08")[0])
            del row["source_timestamp"]
            row["pv1_input_current_a"] = float("nan")
            row["pv2_input_voltage_v"] = True
            write_rows(root / "electricity/pv_inverter.json", [row])
            self.assertEqual(load_samples(root, "2026-06-08", "2026-06-09", POLICY)[0], [])
            samples, quality = load_samples(root, "2026-06-08", "2026-06-09", POLICY, allow_legacy=True)
            self.assertIsNone(samples[0].currents[0])
            self.assertIsNone(samples[0].voltages[1])
            self.assertEqual(quality["pv_accepted_legacy"], 1)

    def test_weather_is_trailing_fresh_bounded_and_requires_three_minutes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = samples_for("2026-06-08")[0]
            write_rows(root / "electricity/pv_inverter.json", [raw_sample(sample)])
            rows = []
            for offset, lux in [(-240, 50000), (-180, 50000), (-120, 50000), (-60, 42000000), (60, 100000)]:
                stamp = datetime.fromtimestamp(sample.epoch + offset, ZONE).isoformat()
                rows.append({"timestamp": stamp, "last_updated": stamp,
                             "state": {"illuminance_lux": lux, "temperature_c": 20}})
            write_rows(root / "weather_station/weather_station.json", rows)
            samples, quality = load_samples(root, "2026-06-08", "2026-06-09", POLICY)
            self.assertEqual(samples[0].lux, 50000)
            self.assertEqual(quality["weather_invalid_measurements"], 1)
            rows[0]["last_updated"] = datetime.fromtimestamp(sample.epoch - 1000, ZONE).isoformat()
            write_rows(root / "weather_station/weather_station.json", rows)
            self.assertIsNone(load_samples(root, "2026-06-08", "2026-06-09", POLICY)[0][0].lux)

    def test_received_after_cutoff_and_malformed_tail_are_not_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = samples_for("2026-06-08")[0]
            late = raw_sample(sample)
            late["timestamp"] = "2026-06-09-00-01-00"
            path = root / "electricity/pv_inverter.json"
            write_rows(path, [late])
            with path.open("a") as handle:
                handle.write('{"unfinished":')
            samples, quality = load_samples(root, "2026-06-08", "2026-06-09", POLICY)
            self.assertFalse(samples)
            self.assertEqual(quality["pv_malformed_rows"], 1)

    def test_dc_consistency_and_explicit_standby_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [raw_sample(s) for s in samples_for("2026-06-08")[:2]]
            rows[0]["total_input_power_kw"] *= .5
            rows[1]["inverter_operating_state_code"] = 40960
            write_rows(root / "electricity/pv_inverter.json", rows)
            samples, _ = load_samples(root, "2026-06-08", "2026-06-09", POLICY)
            self.assertFalse(samples[0].dc_consistent)
            self.assertFalse(samples[1].usable)


class CommandTests(unittest.TestCase):
    def test_command_help_does_not_import_project_or_external_dependencies(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, "-B", "-S", "-m", "services.pv_performance_monitor", "--help"],
                                capture_output=True, text=True, cwd=service.ROOT, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.logs = self.root / "logs"
        self.model_path = self.root / "baseline.json"
        self.state_path = self.root / "shadow-state.json"
        atomic_json(self.model_path, baseline())
        write_rows(self.logs / "electricity/pv_inverter.json", [raw_sample(s) for s in samples_for("2026-06-08")])

    def args(self, command, *extra):
        return service.parser().parse_args([command, "--logs", str(self.logs), "--model", str(self.model_path), *extra])

    def test_preview_is_read_only_and_has_no_notification_mode(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = service.execute(self.args("shadow", "--from", "2026-06-08"), now=datetime(2026, 6, 9, 12, tzinfo=timezone.utc))
        self.assertFalse(result["notifications_enabled"])
        self.assertEqual(result["evaluation_end_exclusive"], "2026-06-09")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_persisted_shadow_catches_up_once_and_rejects_baseline_change(self):
        args = self.args("shadow", "--from", "2026-06-08", "--state", str(self.state_path))
        now = datetime(2026, 6, 9, 12, tzinfo=timezone.utc)
        first = service.execute(args, now=now)
        self.assertEqual(read_json(self.state_path)["last_day"], "2026-06-08")
        second = service.execute(self.args("shadow", "--state", str(self.state_path)), now=now)
        self.assertFalse(second["daily"])
        self.assertFalse(second["events"])
        self.assertEqual(first["state"]["targets"], second["state"]["targets"])
        saved = read_json(self.state_path)
        saved["model_id"] = "wrong"
        atomic_json(self.state_path, saved)
        before = self.state_path.read_bytes()
        with self.assertRaises(ValueError):
            service.execute(self.args("shadow", "--state", str(self.state_path)), now=now)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_current_day_replay_is_rejected(self):
        with self.assertRaises(ValueError):
            service.execute(self.args("replay", "--from", "2026-06-08", "--until", "2026-11-02"), now=NOW)

    def test_outputs_cannot_overwrite_inputs_models_or_state(self):
        for output in (self.logs / "result.json", self.model_path, self.state_path):
            args = self.args("shadow", "--state", str(self.state_path), "--output", str(output))
            with self.assertRaises(ValueError):
                service.execute(args, now=NOW)

    def test_corrupt_state_is_not_silently_reset(self):
        self.state_path.write_text("{partial")
        with self.assertRaises(ValueError):
            service.execute(self.args("shadow", "--state", str(self.state_path)), now=NOW)
        self.assertEqual(self.state_path.read_text(), "{partial")

    def test_lock_excludes_concurrent_state_writers(self):
        lock = self.root / "state.lock"
        with state_lock(lock):
            with self.assertRaises(OSError), state_lock(lock):
                self.fail("Second writer acquired the state lock")

    def test_baseline_cli_builds_a_versioned_file_and_refuses_overwrite(self):
        rows = [raw_sample(s) for day in range(1, 7) for s in samples_for(f"2026-06-{day:02d}")]
        write_rows(self.logs / "electricity/pv_inverter.json", rows)
        destination = self.root / "new-baseline.json"
        args = service.parser().parse_args(["baseline", "--logs", str(self.logs), "--from", "2026-06-01",
                                           "--until", "2026-06-07", "--output", str(destination)])
        built = service.execute(args, now=NOW)
        self.assertGreater(built["points"]["pv1"], 0)
        self.assertEqual(read_json(destination)["model_id"], built["model_id"])
        before = destination.read_bytes()
        with self.assertRaises(ValueError):
            service.execute(args, now=NOW)
        self.assertEqual(destination.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
