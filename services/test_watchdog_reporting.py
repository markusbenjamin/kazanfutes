"""Regression tests for maintenance-only Parasolls and grouped heating reminders."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.device_watchdog import _notify_critical
from utils.device_watchdog import (
    battery_observation, candidates_for, heating_critical_incidents,
    heating_reminder_due, initial_incident_state, policy_for, update_incidents,
)


NOW = datetime(2026, 10, 21, 8, tzinfo=timezone(timedelta(hours=2)))
CONFIG = {
    "heating_reminders": {"enabled": True, "hour": 8},
    "profiles": {
        "critical_danfoss_valve": {"class": "critical", "critical_when_heating_on": True,
                                  "battery_warning_percent": 30, "battery_critical_percent": 3},
        "critical_pump": {"class": "critical", "critical_when_heating_on": True},
        "critical_dependency": {"class": "critical", "critical_when_heating_on": True},
        "boiler_power_plug": {"class": "critical"},
        # Deliberately use the old profile: legacy configuration cannot escalate
        # Parasolls back to critical, including the low-battery flag shortcut.
        "parasoll": {"class": "critical", "battery_warning_percent": 15,
                     "battery_critical_percent": 15, "stale_after_minutes": 60},
    },
}


def inventory():
    state = initial_incident_state()
    for name, profile, category in (
        ("Valve", "critical_danfoss_valve", "danfoss_valve"),
        ("Pump", "critical_pump", "tuya_pump"),
        ("Gateway", "critical_dependency", "zigbee_gateway"),
        ("Boiler plug", "boiler_power_plug", "boiler_power_plug"),
        ("Window", "parasoll", "parasoll"),
    ):
        device_id = "test:" + name
        state["known_devices"][device_id] = {
            "device_id": device_id, "name": name, "profile": profile,
            "category": category, "facts": {"heating_on": True},
        }
        for kind in (("connectivity", "low_battery") if name == "Valve" else ("connectivity",)):
            ident = device_id + ":" + kind
            state["active"][ident] = {
                "incident_id": ident, "device_id": device_id, "device_name": name,
                "category": category, "hardware_type": profile, "kind": kind,
                "class": "revision" if name == "Window" else "critical",
                "message": "Needs attention", "opened_at": "2026-09-10T16:38:25+02:00",
                "immediate_notification_sent_at": "2026-09-10T16:43:01+02:00",
            }
    return state


class HeatingReportingTests(unittest.TestCase):
    def test_before_morning_is_not_due(self):
        self.assertFalse(heating_reminder_due({}, CONFIG, NOW.replace(hour=7, minute=59)))

    def test_old_state_without_marker_is_due(self):
        self.assertTrue(heating_reminder_due({}, CONFIG, NOW))

    def test_can_catch_up_after_missed_scheduler_window(self):
        self.assertTrue(heating_reminder_due({}, CONFIG, NOW.replace(hour=11)))

    def test_delivery_and_empty_check_both_survive_restart(self):
        for key in ("heating_reminder_checked_for", "heating_reminder_sent_for"):
            self.assertFalse(heating_reminder_due({key: "2026-10-21"}, CONFIG, NOW))
            self.assertTrue(heating_reminder_due({key: "2026-10-21"}, CONFIG, NOW + timedelta(days=1)))

    def test_disable_and_custom_hour(self):
        self.assertFalse(heating_reminder_due({}, {"heating_reminders": {"enabled": False}}, NOW))
        self.assertFalse(heating_reminder_due({}, {"heating_reminders": {"hour": 9}}, NOW))

    def test_selects_only_current_heating_critical_incidents(self):
        state = inventory()
        selected = heating_critical_incidents(state, CONFIG)
        self.assertEqual(len(selected), 5)
        self.assertFalse(any(e["device_name"] == "Window" for e in selected.values()))
        state["known_devices"]["test:Valve"]["facts"]["heating_on"] = False
        self.assertEqual(len(heating_critical_incidents(state, CONFIG)), 3)

    def test_nonheating_critical_override_is_not_a_heating_reminder(self):
        state = inventory()
        state["known_devices"]["test:Valve"]["profile"] = "unrelated"
        self.assertEqual(len(heating_critical_incidents(state, CONFIG)), 3)

    @patch("services.device_watchdog.notify_admin")
    def test_old_notified_incidents_repeat_grouped_each_morning(self, mail):
        state = inventory()
        _notify_critical(state, NOW, CONFIG)
        mail.assert_called_once()
        subject, body = mail.call_args.args
        self.assertIn("daily reminder", subject)
        self.assertEqual(body.count("CRITICAL — Valve"), 1)
        self.assertIn("Connectivity", body)
        self.assertIn("Low battery", body)
        self.assertNotIn("Window", body)
        self.assertEqual(state["heating_reminder_sent_for"], "2026-10-21")
        _notify_critical(state, NOW + timedelta(minutes=5), CONFIG)
        self.assertEqual(mail.call_count, 1)
        _notify_critical(copy.deepcopy(state), NOW + timedelta(days=1), CONFIG)
        self.assertEqual(mail.call_count, 2)

    @patch("services.device_watchdog.notify_admin")
    def test_new_immediate_alert_is_not_delayed_until_morning(self, mail):
        state = inventory()
        state["active"]["test:Valve:connectivity"]["immediate_notification_sent_at"] = None
        _notify_critical(state, NOW.replace(hour=6), CONFIG)
        mail.assert_called_once()
        self.assertIn("Valve", mail.call_args.args[1])
        self.assertNotIn("Pump", mail.call_args.args[1])
        self.assertIsNotNone(state["active"]["test:Valve:connectivity"]["immediate_notification_sent_at"])
        self.assertIsNone(state["heating_reminder_sent_for"])

    @patch("services.device_watchdog.notify_admin")
    def test_new_and_reminder_conditions_share_one_email(self, mail):
        state = inventory()
        state["active"]["test:Valve:connectivity"]["immediate_notification_sent_at"] = None
        _notify_critical(state, NOW, CONFIG)
        mail.assert_called_once()
        self.assertEqual(mail.call_args.args[1].count("CRITICAL — Valve"), 1)
        self.assertIsNotNone(state["active"]["test:Valve:connectivity"]["immediate_notification_sent_at"])

    @patch("services.device_watchdog.notify_admin", side_effect=RuntimeError("SMTP unavailable"))
    def test_failed_email_keeps_both_deliveries_pending(self, mail):
        state = inventory()
        state["active"]["test:Valve:connectivity"]["immediate_notification_sent_at"] = None
        _notify_critical(state, NOW, CONFIG)
        self.assertIsNone(state["heating_reminder_checked_for"])
        self.assertIsNone(state["heating_reminder_sent_for"])
        self.assertIsNone(state["active"]["test:Valve:connectivity"]["immediate_notification_sent_at"])
        _notify_critical(state, NOW + timedelta(minutes=5), CONFIG)
        self.assertEqual(mail.call_count, 2)

    @patch("services.device_watchdog.notify_admin")
    def test_empty_morning_is_silent_and_later_new_issue_is_immediate(self, mail):
        state = inventory()
        for e in state["active"].values():
            e["class"] = "revision"
        _notify_critical(state, NOW, CONFIG)
        mail.assert_not_called()
        self.assertEqual(state["heating_reminder_checked_for"], "2026-10-21")
        issue = state["active"]["test:Valve:connectivity"]
        issue.update({"class": "critical", "immediate_notification_sent_at": None})
        _notify_critical(state, NOW.replace(hour=13), CONFIG)
        mail.assert_called_once()
        self.assertNotIn("daily reminder", mail.call_args.args[0])

    @patch("services.device_watchdog.notify_admin")
    def test_resolution_removes_device_from_next_reminder(self, mail):
        state = inventory()
        state["active"] = {k: v for k, v in state["active"].items() if v["device_name"] != "Valve"}
        _notify_critical(state, NOW, CONFIG)
        self.assertNotIn("Valve", mail.call_args.args[1])

    @patch("services.device_watchdog.notify_admin")
    def test_boiler_only_invocation_does_not_send_stale_reminders(self, mail):
        state = inventory()
        _notify_critical(state, NOW)
        mail.assert_not_called()
        self.assertIsNone(state["heating_reminder_checked_for"])

    def test_parasoll_policy_cannot_be_critical_even_with_legacy_override(self):
        device = {"device_id": "zigbee:window", "profile": "parasoll"}
        config = copy.deepcopy(CONFIG)
        config["overrides"] = {"zigbee:window": {"class": "critical"}}
        self.assertEqual(policy_for(device, config)["class"], "revision")

    def test_all_parasoll_battery_and_connectivity_conditions_are_revision(self):
        for raw, low in ((10, False), (0, True), (None, True), (101, False)):
            device = {"device_id": "zigbee:window", "name": "Window", "category": "parasoll",
                      "profile": "parasoll", "facts": {
                          "reachable": False, "last_seen_at": (NOW - timedelta(days=2)).isoformat(),
                          "battery": battery_observation(raw, low, configured_scale="percent_100"),
                      }}
            issues = candidates_for(device, CONFIG, NOW)
            self.assertTrue(issues)
            self.assertTrue(all(e["class"] == "revision" for e in issues))

    def test_existing_parasoll_incident_is_demoted_even_in_partial_scan(self):
        state = inventory()
        incident = state["active"]["test:Window:connectivity"]
        incident["class"] = "critical"
        before = copy.deepcopy(incident)
        updated, opened, solved = update_incidents(state, [], CONFIG, NOW, scope_device_ids=set())
        after = updated["active"][incident["incident_id"]]
        self.assertEqual(after, {**before, "class": "revision"})
        self.assertFalse(opened)
        self.assertFalse(solved)

    def test_current_saved_config_has_noncritical_parasolls_and_8am_reminder(self):
        import json
        from pathlib import Path
        config = json.loads((Path(__file__).resolve().parents[1] / "config/device_watchdog.json").read_text())
        self.assertEqual(config["profiles"]["parasoll"]["class"], "revision")
        self.assertEqual(config["heating_reminders"], {"enabled": True, "hour": 8})
        self.assertEqual(config["profiles"]["critical_danfoss_valve"]["battery_critical_percent"], 3)

    def trv(self, percent, *, heating_on=True, low=False):
        return {"device_id": "test:Valve", "name": "Valve", "category": "danfoss_valve",
                "profile": "critical_danfoss_valve", "facts": {
                    "reachable": True, "heating_on": heating_on,
                    "battery": {"battery_percent": percent, "low_battery": low},
                }}

    def test_trv_battery_boundary_and_warning_band(self):
        for percent, expected in ((31, None), (30, "revision"), (17, "revision"),
                                  (3.5, "revision"), (3, "critical"), (2.5, "critical")):
            with self.subTest(percent=percent):
                issues = candidates_for(self.trv(percent), CONFIG, NOW)
                self.assertEqual([e["class"] for e in issues], [] if expected is None else [expected])

    def test_critical_trv_battery_is_revision_when_heating_is_off(self):
        issues = candidates_for(self.trv(2, heating_on=False), CONFIG, NOW)
        self.assertEqual([e["class"] for e in issues], ["revision"])

    def test_trv_battery_threshold_uses_normalized_percent(self):
        for raw, expected in ((6, "critical"), (7, "revision")):
            device = self.trv(None)
            device["facts"]["battery"] = battery_observation(raw, False, configured_scale="half_percent_200")
            self.assertEqual(candidates_for(device, CONFIG, NOW)[0]["class"], expected)

    def test_hardware_low_flag_does_not_escalate_known_percentage_above_three(self):
        issues = candidates_for(self.trv(17, low=True), CONFIG, NOW)
        self.assertTrue(all(e["class"] == "revision" for e in issues))

    def test_hardware_low_flag_remains_actionable_without_a_usable_percentage(self):
        issues = candidates_for(self.trv(None, low=True), CONFIG, NOW)
        self.assertEqual([e["class"] for e in issues], ["critical"])

    @patch("services.device_watchdog.notify_admin")
    def test_existing_critical_battery_demotes_and_fresh_escalation_emails_once(self, mail):
        state = inventory()
        state["active"] = {"test:Valve:low_battery": state["active"]["test:Valve:low_battery"]}
        state["known_devices"] = {"test:Valve": state["known_devices"]["test:Valve"]}
        old_sent = state["active"]["test:Valve:low_battery"]["immediate_notification_sent_at"]
        state["heating_reminder_checked_for"] = NOW.date().isoformat()
        state, opened, solved = update_incidents(state, [self.trv(17)], CONFIG, NOW)
        entry = state["active"]["test:Valve:low_battery"]
        self.assertEqual(entry["class"], "revision")
        self.assertEqual(entry["immediate_notification_sent_at"], old_sent)
        self.assertFalse(opened)
        self.assertFalse(solved)
        _notify_critical(state, NOW, CONFIG)
        mail.assert_not_called()

        state, opened, solved = update_incidents(state, [self.trv(3)], CONFIG, NOW + timedelta(minutes=5))
        entry = state["active"]["test:Valve:low_battery"]
        self.assertEqual(entry["class"], "critical")
        self.assertIsNone(entry["immediate_notification_sent_at"])
        self.assertFalse(opened)
        self.assertFalse(solved)
        _notify_critical(state, NOW + timedelta(minutes=5), CONFIG)
        mail.assert_called_once()

        state, _, _ = update_incidents(state, [self.trv(2.5)], CONFIG, NOW + timedelta(minutes=10))
        _notify_critical(state, NOW + timedelta(minutes=10), CONFIG)
        mail.assert_called_once()

    def test_battery_replacement_resolves_the_warning(self):
        state, _, _ = update_incidents({}, [self.trv(17)], CONFIG, NOW)
        state, _, solved = update_incidents(state, [self.trv(90)], CONFIG, NOW + timedelta(minutes=5))
        self.assertEqual(len(solved), 1)
        self.assertFalse(state["active"])


if __name__ == "__main__":
    unittest.main()
