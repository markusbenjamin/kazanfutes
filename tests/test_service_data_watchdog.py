from __future__ import annotations

import unittest
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.service_data_watchdog import (
    failed_timer_job_is_reportable,
    evaluate,
    initial_incidents,
    parse_observed_time,
    pv_inverter_candidates,
    render_active_incidents,
    update,
)
from services.parasoll_battery_logger import parasoll_battery_snapshot
from utils.project import ModuleException, load_recent_presence_log


class ServiceDataWatchdogTests(unittest.TestCase):
    def test_presence_reader_accepts_lazy_midnight_rotation(self):
        current_record = {"timestamp": "2026-09-15-00-00-00", "states": {}}

        def load_path(path):
            if path.endswith("presence_all.json.2026-09-14"):
                raise ModuleException("rotated file not created yet")
            return [current_record]

        with patch("utils.project.load_ndjson_to_json_list", side_effect=load_path):
            loaded = load_recent_presence_log(datetime(2026, 9, 15, 0, 0))
        self.assertEqual(loaded, [current_record])

    def test_presence_reader_combines_both_sides_after_rotation(self):
        previous_record = {"timestamp": "2026-09-14-23-59-00", "states": {}}
        current_record = {"timestamp": "2026-09-15-00-00-00", "states": {}}
        with patch(
            "utils.project.load_ndjson_to_json_list",
            side_effect=[[previous_record], [current_record]],
        ):
            loaded = load_recent_presence_log(datetime(2026, 9, 15, 0, 1))
        self.assertEqual(loaded, [previous_record, current_record])

    def test_daily_artifact_does_not_go_stale_before_its_next_window(self):
        now = datetime(2026, 9, 15, 0, 8, tzinfo=timezone.utc)
        relative = "config/scheduling/local_scheduling_files/occupancy.json"
        config = {"streams": {relative: {"kind": "periodic", "max_age_minutes": 1500}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "services").mkdir()
            (root / "services" / "services_and_timers.list").write_text("", encoding="utf-8")
            artifact = root / relative
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}", encoding="utf-8")

            os.utime(artifact, (now.timestamp() - 1391 * 60,) * 2)
            candidates, _, _ = evaluate(root, config, now)
            self.assertEqual(candidates, [])

            os.utime(artifact, (now.timestamp() - 1501 * 60,) * 2)
            candidates, _, _ = evaluate(root, config, now)
            self.assertEqual([item["kind"] for item in candidates], ["data_stale"])

    def test_parasoll_snapshot_groups_resources_and_preserves_raw_battery(self):
        devices = parasoll_battery_snapshot([
            {
                "uniqueid": "00:11:22:33-01-0006", "name": "Door", "manufacturername": "IKEA of Sweden",
                "modelid": "PARASOLL Door/Window Sensor", "config": {"battery": 48, "reachable": True},
                "state": {"lowbattery": False}, "lastseen": "2026-09-13T20:54Z",
            },
            {
                "uniqueid": "00:11:22:33-02-0006", "name": "Door", "manufacturername": "IKEA of Sweden",
                "modelid": "PARASOLL Door/Window Sensor", "config": {"battery": 46, "reachable": True},
                "state": {"lowbattery": True}, "lastseen": "2026-09-13T20:55Z",
            },
            {"name": "Other", "manufacturername": "Other", "modelid": "Sensor"},
        ])
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["resources"], 2)
        self.assertEqual(devices[0]["battery"]["battery_raw"], 46)
        self.assertTrue(devices[0]["battery"]["low_battery"])

        zero = parasoll_battery_snapshot([{
            "uniqueid": "00:11:22:44-01-0006", "name": "Window",
            "manufacturername": "IKEA of Sweden", "modelid": "PARASOLL Door/Window Sensor",
            "config": {"battery": 0, "reachable": True},
            "state": {"lowbattery": False}, "lastseen": "2026-09-13T20:55Z",
        }])[0]["battery"]
        self.assertEqual(zero["battery_raw"], 0)
        self.assertIsNone(zero["battery_percent"])
        self.assertTrue(zero["battery_uninitialized"])

    def test_pv_monitor_distinguishes_unreachable_from_stale_inverter_telemetry(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
        relative = "electricity/pv_inverter_status.json"
        policy = {"max_age_minutes": 15, "source_max_age_minutes": 20}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data" / "logs" / relative
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "timestamp": now.isoformat(), "access_state": "unavailable", "failure_stage": "login",
            }) + "\n", encoding="utf-8")
            candidates = pv_inverter_candidates(root, relative, path, policy, "critical", now)
            self.assertEqual([item["kind"] for item in candidates], ["pv_inverter_unreachable"])

            path.write_text(json.dumps({
                "timestamp": now.isoformat(), "access_state": "reachable", "telemetry_state": "received",
                "source_timestamp": (now - timedelta(minutes=21)).isoformat(),
            }) + "\n", encoding="utf-8")
            candidates = pv_inverter_candidates(root, relative, path, policy, "critical", now)
            self.assertEqual([item["kind"] for item in candidates], ["pv_inverter_not_reporting"])

    def test_pv_monitor_reports_fresh_explicit_zero_voltage_with_optional_ws90_evidence(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
        relative = "electricity/pv_inverter_status.json"
        policy = {
            "max_age_minutes": 15, "source_max_age_minutes": 20, "minimum_dc_voltage_fields": 8,
            "illumination_evidence": {
                "stream": "weather_station/weather_station.json", "timestamp_field": "last_updated",
                "max_age_minutes": 5, "value_path": ["state", "illuminance_lux"], "minimum_lux": 10000,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data" / "logs" / relative
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "timestamp": now.isoformat(), "access_state": "reachable", "telemetry_state": "received",
                "source_timestamp": now.isoformat(), "dc_voltage_state": "all_zero", "dc_voltage_field_count": 8,
            }) + "\n", encoding="utf-8")
            weather = root / "data" / "logs" / "weather_station" / "weather_station.json"
            weather.parent.mkdir(parents=True)
            weather.write_text(json.dumps({
                "last_updated": now.isoformat(), "state": {"illuminance_lux": 26000},
            }) + "\n", encoding="utf-8")
            candidates = pv_inverter_candidates(root, relative, path, policy, "critical", now)
            self.assertEqual([item["kind"] for item in candidates], ["pv_inverter_zero_dc_voltage"])
            self.assertIn("26000 lux", candidates[0]["message"])

            path.write_text(json.dumps({
                "timestamp": now.isoformat(), "access_state": "reachable", "telemetry_state": "received",
                "source_timestamp": now.isoformat(), "dc_voltage_state": "nonzero", "dc_voltage_field_count": 8,
                "active_power_state": "zero",
            }) + "\n", encoding="utf-8")
            self.assertEqual(pv_inverter_candidates(root, relative, path, policy, "critical", now), [])

    def test_pv_service_failure_is_replaced_by_the_pv_diagnostic(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            services = root / "services"
            services.mkdir()
            (services / "services_and_timers.list").write_text(
                "pv_logger.service\npv_logger.timer\n", encoding="utf-8"
            )
            config = {
                "service_overrides": {"pv_logger.service": {"state_monitor": "pv_inverter"}},
                "streams": {},
            }
            timer_facts = {"LoadState": "loaded", "ActiveState": "active"}
            service_facts = {
                "LoadState": "loaded", "Result": "exit-code",
                "ExecMainExitTimestamp": (now - timedelta(minutes=20)).isoformat(),
            }
            with patch(
                "services.service_data_watchdog.systemd_show",
                side_effect=lambda unit: timer_facts if unit.endswith(".timer") else service_facts,
            ):
                candidates, _, _ = evaluate(root, config, now)
            self.assertNotIn("run_failed", [item["kind"] for item in candidates])

    def test_timer_failure_waits_for_the_configured_grace(self):
        now = datetime(2026, 9, 13, 22, 22, tzinfo=timezone.utc)
        facts = {"ExecMainExitTimestamp": (now - timedelta(minutes=9)).isoformat()}
        self.assertFalse(failed_timer_job_is_reportable(facts, {}, {"timer_job_failure_grace_minutes": 10}, now))
        self.assertTrue(failed_timer_job_is_reportable(facts, {}, {"timer_job_failure_grace_minutes": 10}, now + timedelta(minutes=1)))

    def test_status_renderer_shows_empty_and_open_incidents(self):
        self.assertEqual(render_active_incidents([]), "NO ACTIVE SERVICE/DATA INCIDENTS")
        rendered = render_active_incidents([{
            "profile": "revision", "kind": "data_stale", "identifier": "example.json", "message": "Latest valid record is 61 minutes old",
        }])
        self.assertIn("ACTIVE SERVICE/DATA INCIDENTS", rendered)
        self.assertIn("example.json", rendered)

    def test_systemd_timestamp_parses(self):
        self.assertIsNotNone(parse_observed_time("Fri 2026-09-11 14:10:00 CEST"))

    def test_configured_stream_is_not_a_discovery_incident(self):
        config = {"confirmation_runs": 2, "streams": {"known/data.json": {"kind": "periodic"}}}
        state, opened, _ = update(initial_incidents(), [], {"known.service"}, {"known/data.json"}, config, datetime.now(timezone.utc))
        self.assertEqual([item["identifier"] for item in opened], ["known.service"])

    def test_data_failure_opens_after_two_checks(self):
        config = {"confirmation_runs": 2, "streams": {}}
        item = {"id": "output:data_stale", "identifier": "output", "profile": "revision", "kind": "data_stale", "message": "stale"}
        now = datetime.now(timezone.utc)
        state, opened, _ = update(initial_incidents(), [item], set(), set(), config, now)
        self.assertEqual(opened, [])
        state, opened, _ = update(state, [item], set(), set(), config, now)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["kind"], "data_stale")
        state, _, solved = update(state, [], set(), set(), config, now)
        self.assertEqual(len(solved), 1)
        self.assertEqual(solved[0]["status"], "solved")


if __name__ == "__main__":
    unittest.main()
