"""Offline tests: synthetic observations, fake devices/SMTP/cameras, temporary files."""
import ast
import copy
from datetime import datetime
from email import message_from_string
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import os
import smtplib
import types

from utils.heating_monitor import (
    CYCLES, due_notifications, evaluate, mark_delivered, new_state, validate_config,
)
from services import heating_monitor as service

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    return json.loads((ROOT / "config/heating_monitor.json").read_text())


def sample(now=1000, on=True, pump=25, flow=.3, supply=65, heat=2000, available=True):
    def reading(**kw):
        return dict(epoch=now, observed_at="test", error=None, **kw)
    return {"epoch": now, "timestamp": "test",
            "commands": {"available": available, "cycles": {c: on for c in CYCLES},
                         "boiler": on, "master": 1, "updated_at": "test", "error": None},
            "pumps": {c: reading(on=on, power_w=pump) for c in CYCLES},
            "heatmeters": {c: reading(flow_temperature_c=supply, return_temperature_c=40,
                                      volume_flow_m3h=flow, power_w=heat) for c in CYCLES},
            "boilers": {"boiler_1": reading(on=True, power_w=80)},
            "cycle_names": {c: c for c in CYCLES},
            "meter_mapping": {c: int(c) for c in CYCLES}}


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()

    def sequence(self, seconds, **kw):
        state = new_state()
        for offset in range(0, seconds + 1, 60):
            state, _ = evaluate(state, sample(1000 + offset, **kw), self.config)
        return state

    def test_config_requires_confirmed_complete_mapping(self):
        validate_config(self.config)
        bad = copy.deepcopy(self.config)
        bad["cycles"]["2"]["meter"] = 1
        with self.assertRaises(ValueError):
            validate_config(bad)

    def test_healthy_active_and_inactive_heating_do_not_alert(self):
        for opts in ({}, {"on": False, "pump": 0, "flow": 0, "heat": 0, "supply": 20}):
            self.assertFalse(self.sequence(1200, **opts)["incidents"])

    def test_pump_failure_requires_two_minutes(self):
        self.assertFalse(self.sequence(60, pump=0)["incidents"])
        state = self.sequence(120, pump=0)
        self.assertEqual(set(state["incidents"]), {c + ":pump" for c in CYCLES})

    def test_relay_off_is_failure_even_with_nonzero_power(self):
        state = new_state()
        for offset in (0, 60, 120):
            s = sample(1000 + offset)
            s["pumps"]["2"]["on"] = False
            state, _ = evaluate(state, s, self.config)
        self.assertEqual(set(state["incidents"]), {"2:pump"})

    def test_flow_startup_grace_then_three_minutes(self):
        self.assertFalse(self.sequence(240, flow=0)["incidents"])
        self.assertEqual(set(self.sequence(300, flow=0)["incidents"]),
                         {c + ":flow" for c in CYCLES})

    def test_reverse_flow_is_not_treated_as_forward_circulation(self):
        self.assertIn("1:flow", self.sequence(300, flow=-.1)["incidents"])

    def test_thermal_fault_waits_warmup_and_three_bad_checks(self):
        self.assertFalse(self.sequence(660, supply=20, heat=0)["incidents"])
        self.assertIn("1:heat", self.sequence(720, supply=20, heat=0)["incidents"])

    def test_hot_water_and_burner_pause_not_thermal_fault(self):
        self.assertFalse(self.sequence(1200, supply=65, heat=0)["incidents"])

    def test_warming_cold_water_delays_thermal_alert(self):
        state = new_state()
        for minute in range(14):
            state, _ = evaluate(state, sample(1000 + minute * 60, supply=20 + minute*.4, heat=0),
                                self.config)
        self.assertFalse(state["incidents"])

    def test_missing_measurements_never_become_zero_power_or_flow(self):
        state = new_state()
        for offset in range(0, 361, 60):
            s = sample(1000 + offset)
            s["pumps"]["1"] = {"epoch": s["epoch"], "error": "timeout"}
            s["heatmeters"]["2"]["power_w"] = float("nan")
            state, _ = evaluate(state, s, self.config)
        self.assertIn("1:pump_data", state["incidents"])
        self.assertIn("2:meter_data", state["incidents"])
        self.assertNotIn("1:pump", state["incidents"])

    def test_unavailable_boiler_does_not_hide_cycle_fault(self):
        state = new_state()
        for offset in range(0, 361, 60):
            s = sample(1000 + offset, pump=0)
            s["boilers"]["boiler_1"]["error"] = "unreachable"
            state, _ = evaluate(state, s, self.config)
        self.assertIn("monitor:boilers", state["incidents"])
        self.assertIn("1:pump", state["incidents"])

    def test_unknown_commands_never_accumulate_on_time(self):
        state = self.sequence(360, available=False, pump=0)
        self.assertEqual(set(state["incidents"]), {"monitor:commands"})
        self.assertFalse(state["on_since"])

    def test_stale_measurement_does_not_count_as_current(self):
        state = new_state()
        for offset in range(0, 361, 60):
            s = sample(1000 + offset)
            s["pumps"]["1"]["epoch"] -= 1000
            state, _ = evaluate(state, s, self.config)
        self.assertIn("1:pump_data", state["incidents"])

    def test_outage_or_clock_rollback_restarts_pending_fault_timer(self):
        state = self.sequence(60, pump=0)
        for now in (5000, 900):
            new, _ = evaluate(state, sample(now, pump=0), self.config)
            self.assertFalse(new["incidents"])
            self.assertEqual(new["on_since"]["1"], now)

    def test_gap_or_missing_data_cannot_resolve_open_fault(self):
        state = self.sequence(120, pump=0)
        state, _ = evaluate(state, sample(5000, available=False), self.config)
        self.assertTrue(state["incidents"]["1:pump"]["active"])

    def test_five_minute_recovery_and_demand_withdrawal_explained(self):
        for on in (True, False):
            state = self.sequence(120, pump=0)
            events = due_notifications(state, 1120, self.config)
            mark_delivered(state, events, 1120)
            for now in range(1180, 1481, 60):
                state, _ = evaluate(state, sample(now, on=on), self.config)
            incident = state["incidents"]["1:pump"]
            self.assertFalse(incident["active"])
            self.assertIn("Heating demand withdrawn" if not on else "Healthy observations", incident["resolution"])
            self.assertEqual({e["kind"] for e in due_notifications(state, 1480, self.config)}, {"recovery"})

    def test_hourly_reminder_and_sent_recovery_deduplication(self):
        state = self.sequence(120, pump=0)
        first = due_notifications(state, 1120, self.config)
        mark_delivered(state, first, 1120)
        self.assertFalse(due_notifications(state, 4719, self.config))
        self.assertEqual({e["kind"] for e in due_notifications(state, 4720, self.config)}, {"reminder"})
        for now in range(1180, 1481, 60):
            state, _ = evaluate(state, sample(now), self.config)
        mark_delivered(state, due_notifications(state, 1480, self.config), 1480)
        self.assertFalse(due_notifications(state, 1540, self.config))

    def test_state_round_trip_preserves_fault_timing(self):
        state = self.sequence(60, pump=0)
        state = json.loads(json.dumps(state))
        state, _ = evaluate(state, sample(1120, pump=0), self.config)
        self.assertIn("1:pump", state["incidents"])

    def test_cycle_thresholds_are_independent(self):
        self.config["cycles"]["1"]["min_pump_w"] = 50
        self.assertEqual(set(self.sequence(120)["incidents"]), {"1:pump"})


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()

    def test_timed_out_collector_keeps_completed_fresh_device_results(self):
        item = {"id": "1", "reading": {"epoch": time.time(), "on": True, "power_w": 12}}
        with patch.object(service, "bounded_process", return_value=(124, service.MARKER + json.dumps(item), "timeout")):
            result = service.collect_group("pumps", self.config)
        self.assertEqual(result["1"]["power_w"], 12)
        self.assertIn("timeout", result["2"]["error"])

    def test_camera_failure_does_not_attach_old_images(self):
        with patch.object(service, "bounded_process", return_value=(1, "", "camera unavailable")):
            capture = service.capture_visual(self.config)
        self.assertEqual(capture["images"], [])
        self.assertIn("camera unavailable", capture["error"])

    def test_camera_timeout_kills_descendant_process_group(self):
        import sys
        started = time.monotonic()
        code, _, _ = service.bounded_process([sys.executable, "-c", "import time; time.sleep(10)"], .05)
        self.assertEqual(code, 124)
        self.assertLess(time.monotonic() - started, 2)

    def test_dry_run_never_logs_sends_or_captures(self):
        with tempfile.TemporaryDirectory() as d, patch.object(service, "collect_snapshot", return_value=sample()), \
                patch.object(service, "log_observation") as log, patch.object(service, "capture_visual") as camera, \
                patch.object(service, "deliver") as mail, patch("builtins.print"):
            service.run(self.config, Path(d), dry_run=True)
            self.assertFalse(list(Path(d).iterdir()))
            log.assert_not_called()
            camera.assert_not_called()
            mail.assert_not_called()

    def test_failed_delivery_retries_frozen_evidence_without_recapture(self):
        self.config["mode"] = "live"
        state = new_state()
        for now in (1000, 1060, 1120):
            state, _ = evaluate(state, sample(now, pump=0), self.config)
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            service.atomic_json(directory / "state.json", state)
            with patch.object(service, "collect_snapshot", return_value=sample(1180, pump=0)), \
                    patch.object(service, "log_observation"), \
                    patch.object(service, "capture_visual", return_value={"status": "failed", "error": "test", "images": []}) as camera, \
                    patch.object(service, "deliver", return_value=(False, "SMTP down")) as mail, \
                    patch.object(service.time, "time", return_value=1180), patch("builtins.print"):
                service.run(self.config, directory)
            saved = service.read_json(directory / "state.json")
            self.assertIsNotNone(saved["outbox"])
            self.assertIsNone(saved["incidents"]["1:pump"]["notified_at"])
            with patch.object(service, "collect_snapshot", return_value=sample(1240, pump=0)), \
                    patch.object(service, "log_observation"), patch.object(service, "capture_visual") as camera, \
                    patch.object(service, "deliver") as mail, patch.object(service.time, "time", return_value=1240), \
                    patch("builtins.print"):
                service.run(self.config, directory)
                camera.assert_not_called()
                mail.assert_not_called()

    def test_command_changes_during_reading_do_not_count_continuous_on(self):
        before = sample()["commands"]
        after = copy.deepcopy(before)
        after["cycles"]["1"] = False
        setup = {"cycles": {c: {"name": c} for c in CYCLES}}
        with patch.object(service, "read_commands", side_effect=[before, after]), \
                patch.object(service, "collect_group", return_value={}), patch.object(service, "read_json", return_value=setup):
            result = service.collect_snapshot(self.config)
        self.assertIsNone(result["commands"]["cycles"]["1"])
        self.assertTrue(result["commands"]["cycles"]["2"])

    def test_master_off_overrides_stale_control_file(self):
        with patch.object(service, "read_json", return_value={"system": 0}):
            result = service.read_commands(self.config)
        self.assertTrue(result["available"])
        self.assertFalse(any(result["cycles"].values()))

    def test_stale_commands_are_unavailable(self):
        with patch.object(service, "read_json", side_effect=[{"system": 1},
                         {"last_updated": "2020-01-01-00-00-00", "cycles": {c: 1 for c in CYCLES}, "boiler": 1}]):
            self.assertFalse(service.read_commands(self.config)["available"])

    def test_report_contains_all_cycles_boilers_and_capture_failure(self):
        from utils.heating_monitor import render_report
        s = sample()
        state, _ = evaluate(new_state(), s, self.config)
        report = render_report(s, state, [], {"status": "failed", "error": "Camera unplugged"})
        for c in CYCLES:
            self.assertIn("Cycle " + c, report)
        self.assertIn("boiler_1", report)
        self.assertIn("Camera unplugged", report)


class EmailTests(unittest.TestCase):
    def test_backward_compatibility_attachments_timeout_and_quit_failure(self):
        source = (ROOT / "utils/project.py").read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "send_email")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            creds = root / "config/secrets_and_env"
            creds.mkdir(parents=True)
            (creds / "gmail_login").write_text("sender@example.invalid\nFAKE_TEST_PASSWORD\n")
            image = root / "pressure.jpg"
            image.write_bytes(b"FAKE_JPEG_FOR_MIME_TEST")
            env = {"os": os, "json": json, "get_project_root": lambda: str(root),
                   "report": lambda *a, **kw: None, "ModuleException": RuntimeError}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "extracted_send_email", "exec"), env)
            for attachments in (None, [image]):
                smtp = Mock()
                smtp.quit.side_effect = OSError("connection closed after acceptance")
                with patch.object(smtplib, "SMTP", return_value=smtp) as factory:
                    self.assertTrue(env["send_email"]("admin@example.invalid", "test", "body",
                                                     attachments=attachments, timeout=5))
                factory.assert_called_once_with("smtp.gmail.com", 587, timeout=5)
                message = message_from_string(smtp.sendmail.call_args.args[2])
                parts = [p for p in message.walk() if p.get_content_disposition() == "attachment"]
                self.assertEqual(len(parts), 1 if attachments else 0)
                if parts:
                    self.assertEqual(parts[0].get_content_type(), "image/jpeg")
                    self.assertEqual(parts[0].get_payload(decode=True), image.read_bytes())


if __name__ == "__main__":
    unittest.main()
