"""Connectivity lifecycle regressions. No network, logs, or live-state writes."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from utils.device_watchdog import (
    update_incidents, initial_incident_state, queue_resolution_notifications,
    digest_incident_changes, render_connectivity_observations,
)
from services.device_watchdog import collect_shelly, collect_deconz

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
CONFIG = {
    "connectivity": {"enabled": True, "resolution_only_if_notified": True},
    "profiles": {
        "critical_danfoss_valve": {"class": "critical", "critical_when_heating_on": True,
            "stale_after_minutes": 240, "connectivity_silence_minutes": 60,
            "connectivity_confirm_minutes": 15, "unreachable_min_silence_minutes": 45},
        "parasoll": {"class": "critical", "stale_after_minutes": 1440,
            "battery_critical_percent": 15, "open_after_runs": 1},
        "infrastructure": {"class": "revision", "stale_after_minutes": 1440},
        "boiler_power_plug": {"class": "critical", "open_after_runs": 1},
    },
}


def trv(age=120, reachable=False, at=NOW):
    return {"device_id": "zigbee:trv", "name": "TRV", "profile": "critical_danfoss_valve",
            "facts": {"reachable": reachable, "last_seen_at": (at-timedelta(minutes=age)).isoformat(), "heating_on": True}}


class ConnectivityTests(unittest.TestCase):
    def advance(self, state, device, offset=0):
        return update_incidents(state, [device], CONFIG, NOW+timedelta(minutes=offset))

    def test_stale_trv_opens_even_with_cached_true_flag(self):
        state, opened, _ = self.advance({}, trv(reachable=True))
        self.assertEqual([item["kind"] for item in opened], ["connectivity"])

    def test_fresh_radio_outweighs_false_flag(self):
        state, opened, _ = self.advance({}, trv(age=1))
        self.assertEqual(opened, [])
        self.assertEqual(state["connectivity_tracking"]["zigbee:trv"]["status"], "suspected")

    def test_wall_clock_not_poll_count_controls_soft_failure(self):
        state = {}
        for offset in (0, 1, 2, 3, 4, 5):
            state, opened, _ = self.advance(state, trv(age=45+offset), offset)
            self.assertFalse(opened)
        state, opened, _ = self.advance(state, trv(age=60), 15)
        self.assertEqual(len(opened), 1)

    def test_trv_false_flag_fortyfive_minutes_plus_persistence(self):
        state, _, _ = self.advance({}, trv(age=30))
        state, opened, _ = self.advance(state, trv(age=45), 15)
        self.assertEqual(len(opened), 1)

    def test_flag_flapping_does_not_resolve_stale_episode(self):
        device = trv()
        state, _, _ = self.advance({}, device)
        marker = "already emailed"
        state["active"]["zigbee:trv:connectivity"]["immediate_notification_sent_at"] = marker
        for offset in (5, 10, 15, 20):
            device["facts"]["reachable"] = offset % 10 == 0
            state, opened, solved = self.advance(state, device, offset)
            self.assertEqual((opened, solved), ([], []))
            self.assertEqual(state["active"]["zigbee:trv:connectivity"]["immediate_notification_sent_at"], marker)

    def test_recovery_needs_ten_minutes_and_two_distinct_radio_reports(self):
        state, _, _ = self.advance({}, trv())
        fresh = trv(age=0, reachable=True, at=NOW+timedelta(minutes=5))
        state, _, solved = self.advance(state, fresh, 5)
        self.assertFalse(solved)
        state, _, solved = self.advance(state, fresh, 15)
        self.assertFalse(solved)  # cached timestamp isn't a second report
        fresh["facts"]["last_seen_at"] = (NOW+timedelta(minutes=16)).isoformat()
        state, _, solved = self.advance(state, fresh, 20)
        self.assertEqual(len(solved), 1)

    def test_failed_probe_resets_recovery_hold(self):
        device = {"device_id": "shelly:aa:bb:cc:dd:ee:ff", "name": "Shelly", "profile": "infrastructure", "facts": {"collection_error": "timeout"}}
        state, _, _ = self.advance({}, device)
        state, opened, _ = self.advance(state, device, 10)
        self.assertEqual(len(opened), 1)
        healthy = copy.deepcopy(device)
        healthy["facts"] = {"reachable": True}
        state, _, _ = self.advance(state, healthy, 15)
        state, _, _ = self.advance(state, device, 20)
        state, _, solved = self.advance(state, healthy, 25)
        self.assertFalse(solved)
        state, _, solved = self.advance(state, healthy, 35)
        self.assertEqual(len(solved), 1)

    def test_source_failure_cannot_resolve_or_report_child_missing(self):
        device = trv()
        device["dependencies"] = ["gateway:deconz"]
        state, _, _ = self.advance({}, device)
        gateway = {"device_id": "gateway:deconz", "name": "gateway", "profile": "infrastructure", "facts": {"collection_error": "timeout"}}
        for offset in (5, 20):
            state, opened, solved = update_incidents(state, [gateway], CONFIG, NOW+timedelta(minutes=offset))
            self.assertFalse(solved)
            self.assertFalse(any(item["device_id"] == "zigbee:trv" for item in opened))

    def test_missing_requires_elapsed_time_and_preserves_heating_severity(self):
        state, _, _ = self.advance({}, trv(age=0, reachable=True))
        state, opened, _ = update_incidents(state, [], CONFIG, NOW+timedelta(minutes=5))
        self.assertFalse(opened)
        state, opened, _ = update_incidents(state, [], CONFIG, NOW+timedelta(minutes=20))
        self.assertEqual(opened[0]["class"], "critical")

    def test_source_uncertainty_propagates_to_absent_peripherals(self):
        state = initial_incident_state()
        for identifier, dependency in (("host", "collector:source"), ("probe", "host")):
            state["known_devices"][identifier] = {"device_id": identifier, "name": identifier, "profile": "infrastructure", "dependencies": [dependency]}
        source = {"device_id": "collector:source", "name": "source", "profile": "infrastructure", "facts": {"collection_error": "failed"}}
        state, _, _ = self.advance(state, source)
        state, opened, _ = self.advance(state, source, 30)
        self.assertEqual([item["device_id"] for item in opened], ["collector:source"])

    def test_parasoll_soft_flags_wait_for_silence_not_battery(self):
        device = trv(age=60)
        device["profile"] = "parasoll"
        device["facts"]["battery"] = {"battery_percent": 10}
        state, opened, _ = self.advance({}, device)
        self.assertEqual([item["kind"] for item in opened], ["low_battery"])
        state, _, _ = self.advance(state, device, 10)
        self.assertIn("suspected", render_connectivity_observations(state))
        device["facts"]["last_seen_at"] = (NOW-timedelta(days=2)).isoformat()
        state, opened, _ = self.advance(state, device, 15)
        self.assertEqual([item["kind"] for item in opened], ["connectivity"])

    def test_measurement_stale_separate_from_radio_connectivity(self):
        device = trv(age=0, reachable=True)
        device["facts"]["measurement_updated_at"] = {"temperature_c": (NOW-timedelta(hours=8)).isoformat()}
        state, opened, _ = self.advance({}, device)
        self.assertEqual([item["kind"] for item in opened], ["measurement_stale_temperature_c"])

    def test_quiet_mains_flags_are_not_proof_of_failure(self):
        device = trv(age=5000)
        device["profile"] = "infrastructure"
        device["facts"]["quiet_mains"] = True
        state, opened, _ = self.advance({}, device)
        state, opened, _ = self.advance(state, device, 60)
        self.assertFalse(opened)
        self.assertEqual(state["connectivity_tracking"]["zigbee:trv"]["status"], "suspected")

    def test_boiler_off_remains_immediate_and_scoped_run_preserves_other_state(self):
        state, _, _ = self.advance({}, trv())
        existing = copy.deepcopy(state["active"]["zigbee:trv:connectivity"])
        tracking = copy.deepcopy(state["connectivity_tracking"])
        plug = {"device_id": "boiler:1", "name": "boiler1", "profile": "boiler_power_plug", "facts": {"armed": True, "output_on": False, "reachable": True}}
        state, opened, solved = update_incidents(state, [plug], CONFIG, NOW+timedelta(minutes=1), scope_device_ids={"boiler:1"})
        self.assertEqual([item["kind"] for item in opened], ["output_off"])
        self.assertEqual(state["active"]["zigbee:trv:connectivity"], existing)
        self.assertEqual(state["connectivity_tracking"], tracking)
        self.assertFalse(solved)

    def test_migration_preserves_email_and_digest_dedup(self):
        device = {"device_id": "shelly:aa:bb:cc:dd:ee:ff", "name": "radiator", "profile": "infrastructure", "facts": {"collection_error": "timeout"}}
        state = initial_incident_state()
        for identifier, kind in (("shelly:radiator", "missing"), (device["device_id"], "unreachable")):
            key = f"{identifier}:{kind}"
            state["known_devices"][identifier] = {**device, "device_id": identifier}
            state["active"][key] = {"device_id": identifier, "device_name": "radiator", "kind": kind, "incident_id": key, "class": "revision", "opened_at": NOW.isoformat(), "immediate_notification_sent_at": "previous delivery"}
        state["digest_last_incident_inventory"] = list(state["active"].values())
        state, opened, solved = self.advance(state, device)
        self.assertFalse(opened or solved)
        self.assertEqual(len(state["active"]), 1)
        self.assertEqual(digest_incident_changes(state), [])
        self.assertNotIn("shelly:radiator", state["known_devices"])
        self.assertEqual(next(iter(state["active"].values()))["immediate_notification_sent_at"], "previous delivery")

    def test_unannounced_revision_resolution_stays_history_only(self):
        state = {"resolution_only_if_notified": True}
        solved = {"incident_id": "x:connectivity", "device_id": "x"}
        queue_resolution_notifications(state, [solved])
        self.assertFalse(state["pending_resolution_notifications"])
        state["digest_last_incident_inventory"] = [solved]
        queue_resolution_notifications(state, [solved])
        self.assertEqual(len(state["pending_resolution_notifications"]), 1)

    def test_shelly_resolution_failure_keeps_configured_mac(self):
        config = {"discovery": {"cache_relative_path": "unused"}, "radiator_devices": [], "submeters": {"unit": {}}, "devices": {"unit": {"mac": "AABBCCDDEEFF"}}}
        resolver = SimpleNamespace(resolve_many=lambda specs: ({}, {"unit": "timeout"}))
        with patch("services.device_watchdog.load_shelly_config", return_value=config), patch("services.device_watchdog.build_shelly_resolver", return_value=resolver), patch("services.device_watchdog.read_json", return_value={}):
            devices = collect_shelly()
        self.assertEqual(devices[1]["device_id"], "shelly:aa:bb:cc:dd:ee:ff")

    def test_device_with_no_initial_timestamp_eventually_fails(self):
        device = trv()
        device["facts"]["last_seen_at"] = None
        state, opened, _ = self.advance({}, device)
        self.assertFalse(opened)
        state, opened, _ = self.advance(state, device, 60)
        self.assertEqual(len(opened), 1)

    def test_delayed_recovery_is_not_sent_for_reopened_episode(self):
        state, _, _ = self.advance({}, trv())
        identifier = "zigbee:trv:connectivity"
        state["pending_resolution_notifications"] = {identifier: copy.deepcopy(state["active"][identifier])}
        state, _, _ = self.advance(state, trv(), 5)
        self.assertFalse(state["pending_resolution_notifications"])

    def test_partial_read_does_not_clear_old_low_battery(self):
        device = trv(age=0, reachable=True)
        device["profile"] = "parasoll"
        device["facts"]["battery"] = {"battery_percent": 5}
        state, _, _ = self.advance({}, device)
        device["facts"]["battery"] = {"battery_percent": None}
        state, _, solved = self.advance(state, device, 5)
        self.assertFalse(solved)

    def test_manual_only_battery_markers_do_not_get_connectivity_tracking(self):
        device = {"device_id": "zigbee:manual", "name": "manual", "profile": "parasoll", "facts": {"manual_only": True, "temporary_nonrechargeable_battery": True}}
        state, opened, _ = self.advance({}, device)
        state, opened, _ = self.advance(state, device, 5000)
        self.assertFalse(opened)
        self.assertNotIn("zigbee:manual", state.get("connectivity_tracking", {}))

    def test_recovering_heating_issue_becomes_revision_when_heating_off(self):
        state, _, _ = self.advance({}, trv())
        device = trv(age=0, reachable=True, at=NOW+timedelta(minutes=5))
        device["facts"]["heating_on"] = False
        state, _, _ = self.advance(state, device, 5)
        self.assertEqual(state["active"]["zigbee:trv:connectivity"]["class"], "revision")

    def test_dead_measurement_not_duplicated_as_new_issue_during_outage(self):
        device = trv()
        device["facts"]["measurement_updated_at"] = {"temperature_c": (NOW-timedelta(days=1)).isoformat()}
        state, opened, _ = self.advance({}, device)
        self.assertEqual([item["kind"] for item in opened], ["connectivity"])

    def test_deconz_retains_measurement_freshness(self):
        raw = {"uniqueid": "aa:bb:cc:dd:ee:ff:00:11-01-0402", "name": "sensor", "type": "ZHATemperature", "lastseen": "2026-10-18T12:00Z", "state": {"temperature": 2150, "lastupdated": "2026-10-18T10:00:00Z"}, "config": {"reachable": True}}
        session = SimpleNamespace(sensors={"1": SimpleNamespace(raw=raw)}, lights={})
        with patch("services.device_watchdog.read_deconz_state", return_value=session), patch("services.device_watchdog.read_deconz_device_inventory", return_value=([], "0011223344556677")):
            devices = collect_deconz({})
        sensor = next(item for item in devices if item["device_id"].startswith("zigbee:"))
        self.assertIn("temperature_c", sensor["facts"]["measurement_updated_at"])
        self.assertFalse(sensor["facts"]["quiet_mains"])


if __name__ == "__main__":
    unittest.main()
