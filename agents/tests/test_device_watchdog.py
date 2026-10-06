from __future__ import annotations

import unittest
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.device_watchdog import (
    apply_manual_state,
    clear_parasoll_temporary_battery,
    incomplete_deconz_device_ids,
    initial_manual_state,
    read_heating_context,
    set_parasoll_temporary_battery,
)
from utils.device_watchdog import (
    INCIDENTS_RELATIVE_PATH,
    MANUAL_STATE_RELATIVE_PATH,
    apply_battery_scale_learning,
    atomic_write_json,
    battery_observation,
    build_digest,
    digest_delivery_needed,
    digest_due,
    digest_incident_changes,
    digest_incident_inventory,
    initial_incident_state,
    render_grouped_report,
    render_table,
    read_json,
    snapshot,
    update_incidents,
)


CONFIG = {
    "profiles": {
        "critical": {
            "class": "critical",
            "critical_when_heating_on": True,
            "open_after_runs": 2,
            "stale_after_minutes": None,
            "battery_warning_percent": None,
            "battery_critical_percent": None,
        },
        "gas_meter": {
            "class": "revision",
            "open_after_runs": 1,
            "stale_after_minutes": None,
            "event_after_minutes": 2160,
        },
    },
    "overrides": {},
}


class DeviceWatchdogTests(unittest.TestCase):
    def test_incomplete_deconz_devices_exclude_coordinator_and_known_resources(self):
        devices = [
            "00:21:2e:ff:ff:08:6a:33",
            "a0:85:e3:ff:fe:c8:04:90",
            "cc:ba:97:ff:fe:c9:d9:34",
        ]
        known = {"a0:85:e3:ff:fe:c8:04:90"}
        self.assertEqual(
            incomplete_deconz_device_ids(devices, known, "00212EFFFF086A33"),
            ["cc:ba:97:ff:fe:c9:d9:34"],
        )

    def test_incomplete_interview_opens_a_revision_incident(self):
        now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        config = {"profiles": {"zigbee": {
            "class": "revision", "open_after_runs": 1, "stale_after_minutes": None,
        }}, "overrides": {}}
        device = [{
            "device_id": "zigbee:cc:ba:97:ff:fe:c9:d9:34",
            "name": "oktopusz_1_radiator_shelly",
            "category": "incomplete_zigbee_device",
            "hardware_type": "Incomplete deCONZ Zigbee device",
            "profile": "zigbee",
            "facts": {
                "incomplete_interview": True,
                "ieee_address": "cc:ba:97:ff:fe:c9:d9:34",
            },
        }]
        _, opened, _ = update_incidents(initial_incident_state(), device, config, now)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["kind"], "incomplete_interview")
        self.assertEqual(opened[0]["class"], "revision")

    def test_battery_normalizes_only_known_or_proven_scale(self):
        self.assertEqual(
            battery_observation(40, False, configured_scale="half_percent_200")["battery_percent"],
            20,
        )
        ambiguous = battery_observation(40, False)
        self.assertEqual(ambiguous["battery_scale"], "unknown")
        self.assertIsNone(ambiguous["battery_percent"])
        automatic = battery_observation(160, False)
        self.assertEqual(automatic["battery_scale"], "half_percent_200")
        self.assertEqual(automatic["battery_percent"], 80)

    def test_deconz_zero_battery_is_unknown_unless_low_battery_is_explicit(self):
        uninitialized = battery_observation(
            0, False, configured_scale="percent_100", zero_is_unknown=True,
        )
        self.assertEqual(uninitialized["battery_raw"], 0)
        self.assertIsNone(uninitialized["battery_percent"])
        self.assertTrue(uninitialized["battery_uninitialized"])

        explicit_low = battery_observation(
            0, True, configured_scale="percent_100", zero_is_unknown=True,
        )
        self.assertEqual(explicit_low["battery_percent"], 0)
        self.assertFalse(explicit_low["battery_uninitialized"])
        self.assertTrue(explicit_low["low_battery"])

    def test_battery_learning_preserves_deconz_zero_sentinel(self):
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        state = initial_incident_state()
        devices = [{
            "device_id": "zigbee:parasoll", "name": "Parasoll", "facts": {
                "battery": battery_observation(
                    0, False, configured_scale="percent_100", zero_is_unknown=True,
                ),
            },
        }]
        apply_battery_scale_learning(devices, state, {}, now)
        battery = devices[0]["facts"]["battery"]
        self.assertIsNone(battery["battery_percent"])
        self.assertTrue(battery["battery_uninitialized"])
        self.assertTrue(battery["battery_zero_is_unknown"])

    def test_critical_incident_opens_after_two_runs_and_then_solves(self):
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        failed = [{
            "device_id": "tuya:pump:1", "name": "Heating pump 1",
            "category": "tuya_pump", "profile": "critical",
            "facts": {"collection_error": "timeout", "heating_on": True},
        }]
        state, opened, solved = update_incidents(initial_incident_state(), failed, CONFIG, now)
        self.assertEqual(opened, [])
        self.assertEqual(solved, [])
        state, opened, solved = update_incidents(state, failed, CONFIG, now + timedelta(minutes=5))
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["class"], "critical")
        self.assertEqual(opened[0]["hardware_type"], "Tuya smart plug")
        self.assertIn("TYPE", render_table(state))
        self.assertIn("Tuya smart plug", render_table(state))
        healthy = [{
            "device_id": "tuya:pump:1", "name": "Heating pump 1",
            "category": "tuya_pump", "profile": "critical",
            "facts": {"reachable": True, "measurements": {}},
        }]
        state, opened, solved = update_incidents(state, healthy, CONFIG, now + timedelta(minutes=10))
        self.assertEqual(opened, [])
        self.assertEqual(len(solved), 1)
        self.assertEqual(solved[0]["status"], "solved")

    def test_gas_no_pulse_is_a_revision_incident(self):
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        device = [{
            "device_id": "gas:meter", "name": "Gas meter", "category": "gas_meter",
            "profile": "gas_meter", "facts": {"last_event_at": (now - timedelta(hours=37)).isoformat()},
        }]
        state, opened, _ = update_incidents(initial_incident_state(), device, CONFIG, now)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["kind"], "event_stalled")
        self.assertEqual(opened[0]["class"], "revision")
        table = snapshot(device, state, now)
        self.assertEqual(table["summary"]["revision_incidents"], 1)

    def test_ambiguous_battery_becomes_conservative_after_learning_window(self):
        now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        state = initial_incident_state()
        device = [{
            "device_id": "zigbee:one", "name": "Battery device", "facts": {
                "battery": battery_observation(80, False),
            },
        }]
        learning_config = {"battery_scales": {"learning_days": 7, "learning_min_samples": 2}}
        apply_battery_scale_learning(device, state, learning_config, now)
        self.assertEqual(device[0]["facts"]["battery"]["battery_scale"], "unknown")
        apply_battery_scale_learning(device, state, learning_config, now + timedelta(days=7))
        learned = device[0]["facts"]["battery"]
        self.assertEqual(learned["battery_scale"], "conservative_half_percent_200")
        self.assertEqual(learned["battery_percent"], 40)

    def test_daily_digest_is_due_once_each_day_at_the_configured_hour(self):
        config = {"digest": {"frequency": "daily", "hour": 8, "minute_window": 15}}
        now = datetime(2026, 9, 11, 8, 4, tzinfo=timezone.utc)
        self.assertTrue(digest_due({}, config, now))
        self.assertFalse(digest_due({"digest_sent_for": now.date().isoformat()}, config, now))
        self.assertFalse(digest_due({"digest_checked_for": now.date().isoformat()}, config, now))
        self.assertFalse(digest_due({}, config, now.replace(hour=9)))

    def test_digest_delivery_is_based_on_incident_identity_and_severity(self):
        config = {"digest": {"send_when_empty": False}}
        incidents = initial_incident_state()
        incidents["active"] = {
            "zigbee:one:stale": {
                "incident_id": "zigbee:one:stale",
                "device_id": "zigbee:one",
                "kind": "stale",
                "class": "revision",
                "message": "Last seen 60 minutes ago",
                "evidence": {"age_minutes": 60},
            }
        }
        self.assertTrue(digest_delivery_needed(incidents, config))
        incidents["digest_last_incident_inventory"] = digest_incident_inventory(incidents)

        incidents["active"]["zigbee:one:stale"]["message"] = "Last seen 65 minutes ago"
        incidents["active"]["zigbee:one:stale"]["evidence"] = {"age_minutes": 65}
        self.assertFalse(digest_delivery_needed(incidents, config))

        incidents["active"]["zigbee:one:stale"]["class"] = "critical"
        self.assertFalse(digest_delivery_needed(incidents, config))

    def test_digest_delivery_reports_when_the_last_incident_is_solved(self):
        config = {"digest": {"send_when_empty": False}}
        incidents = initial_incident_state()
        self.assertFalse(digest_delivery_needed(incidents, config))
        incidents["digest_last_incident_inventory"] = [{
            "incident_id": "zigbee:one:stale",
            "device_id": "zigbee:one",
            "kind": "stale",
            "class": "revision",
        }]
        self.assertTrue(digest_delivery_needed(incidents, config))

    def test_digest_contains_only_added_and_resolved_changes_grouped_by_device(self):
        incidents = initial_incident_state()
        incidents["known_devices"] = {
            "zigbee:one": {"name": "Panel sensor", "hardware_type": "Maker Model"},
        }
        incidents["digest_last_incident_inventory"] = [{
            "incident_id": "zigbee:one:stale", "device_id": "zigbee:one",
            "kind": "stale", "class": "revision",
        }]
        incidents["active"] = {
            "zigbee:one:unreachable": {
                "incident_id": "zigbee:one:unreachable", "device_id": "zigbee:one",
                "device_name": "Panel sensor", "hardware_type": "Maker Model",
                "class": "revision", "kind": "unreachable", "message": "Device reports unreachable",
            },
        }
        changes = digest_incident_changes(incidents)
        self.assertEqual({item["change"] for item in changes}, {"added", "resolved"})
        digest = build_digest(incidents, datetime(2026, 9, 13, tzinfo=timezone.utc), "daily")
        self.assertEqual(digest.count("REVISION — Panel sensor"), 2)
        self.assertLess(digest.index("ADDED INCIDENTS"), digest.index("RESOLVED INCIDENTS"))
        added, resolved = digest.split("RESOLVED INCIDENTS")
        self.assertIn("Unreachable: Device reports unreachable", added)
        self.assertNotIn("Stale", added)
        self.assertIn("Stale", resolved)
        self.assertNotIn("Unreachable", resolved)
        self.assertNotIn("ACTIVE DEVICE INCIDENTS", digest)

    def test_email_report_groups_multiple_conditions_under_one_device(self):
        incidents = {"active": {
            "zigbee:one:stale": {
                "incident_id": "zigbee:one:stale", "device_id": "zigbee:one",
                "device_name": "Panel sensor", "hardware_type": "Maker Model",
                "class": "revision", "kind": "stale", "message": "Last seen yesterday",
            },
            "zigbee:one:unreachable": {
                "incident_id": "zigbee:one:unreachable", "device_id": "zigbee:one",
                "device_name": "Panel sensor", "hardware_type": "Maker Model",
                "class": "revision", "kind": "unreachable", "message": "Device reports unreachable",
            },
        }}
        report = render_grouped_report(incidents)
        self.assertEqual(report.count("Panel sensor"), 1)
        self.assertIn("Stale: Last seen yesterday", report)
        self.assertIn("Unreachable: Device reports unreachable", report)
        digest = build_digest(incidents, datetime(2026, 9, 13, tzinfo=timezone.utc), "daily")
        self.assertEqual(digest.count("Panel sensor"), 1)

    def test_heating_fault_severity_tracks_master_switch(self):
        now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        config = {"profiles": {"heating": {
            "class": "critical", "critical_when_heating_on": True,
            "open_after_runs": 1, "stale_after_minutes": None,
        }}, "overrides": {}}
        device = [{
            "device_id": "tuya:pump:1", "name": "Heating pump 1",
            "category": "tuya_pump", "profile": "heating",
            "facts": {"collection_error": "timeout", "heating_on": False},
        }]
        state, opened, _ = update_incidents(initial_incident_state(), device, config, now)
        self.assertEqual(opened[0]["class"], "revision")
        device[0]["facts"]["heating_on"] = True
        state, _, _ = update_incidents(state, device, config, now + timedelta(minutes=5))
        self.assertEqual(state["active"]["tuya:pump:1:unreachable"]["class"], "critical")
        device[0]["facts"]["heating_on"] = None
        state, _, _ = update_incidents(state, device, config, now + timedelta(minutes=10))
        self.assertEqual(state["active"]["tuya:pump:1:unreachable"]["class"], "revision")

    def test_heating_context_uses_system_master_switch(self):
        config = {"heating_context": {
            "source_relative_path": "config/heating_switch.json", "field": "system",
        }}
        with patch("services.device_watchdog.get_project_root", return_value="/project"), \
                patch("services.device_watchdog.read_json", return_value={"system": 1}) as reader:
            self.assertIs(read_heating_context(config)["heating_on"], True)
            self.assertTrue(reader.call_args.args[0].replace("\\", "/").endswith("/config/heating_switch.json"))
        with patch("services.device_watchdog.get_project_root", return_value="/project"), \
                patch("services.device_watchdog.read_json", return_value={"system": 0}):
            self.assertIs(read_heating_context(config)["heating_on"], False)

    def test_manual_parasoll_temporary_battery_lifecycle(self):
        now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        device_id = "zigbee:parasoll-one"
        known = {
            "device_id": device_id, "name": "Kisudvar ajto", "category": "parasoll",
            "profile": "parasoll", "hardware_type": "IKEA PARASOLL", "dependencies": ["gateway:deconz"],
        }
        config = {"profiles": {"parasoll": {
            "class": "revision", "open_after_runs": 2, "stale_after_minutes": None,
            "battery_warning_percent": None, "battery_critical_percent": None,
        }}, "overrides": {}}
        with tempfile.TemporaryDirectory() as project_root:
            os.makedirs(os.path.join(project_root, "system"))
            incident_state = initial_incident_state()
            incident_state["known_devices"][device_id] = known
            atomic_write_json(os.path.join(project_root, INCIDENTS_RELATIVE_PATH), incident_state)

            name, changed = set_parasoll_temporary_battery(project_root, "kisudvar AJTO")
            self.assertTrue(changed)
            self.assertEqual(name, "Kisudvar ajto")
            manual = read_json(os.path.join(project_root, MANUAL_STATE_RELATIVE_PATH), initial_manual_state())
            self.assertIn("Kisudvar ajto", manual["parasoll_temporary_batteries"])

            devices = []
            apply_manual_state(devices, manual, incident_state)
            self.assertTrue(devices[0]["facts"]["manual_only"])
            state, opened, _ = update_incidents(incident_state, devices, config, now)
            self.assertEqual(opened[0]["kind"], "temporary_battery")
            self.assertEqual(opened[0]["class"], "revision")
            self.assertEqual(opened[0]["open_after_runs"], 1)
            self.assertEqual(opened[0]["dependencies"], [])

            name, changed = clear_parasoll_temporary_battery(project_root, "Kisudvar ajto")
            self.assertTrue(changed)
            self.assertEqual(name, "Kisudvar ajto")
            cleared = read_json(os.path.join(project_root, MANUAL_STATE_RELATIVE_PATH), initial_manual_state())
            self.assertEqual(cleared["parasoll_temporary_batteries"], {})
            state, _, solved = update_incidents(state, [], config, now + timedelta(minutes=5))
            self.assertEqual(solved[0]["kind"], "temporary_battery")


if __name__ == "__main__":
    unittest.main()
