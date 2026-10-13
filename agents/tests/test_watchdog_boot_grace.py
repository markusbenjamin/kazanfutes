"""Startup notification delay for the service and data watchdog."""

import unittest
from unittest.mock import patch

from services.service_data_watchdog import in_boot_notification_grace, notify_opened


class WatchdogBootGraceTests(unittest.TestCase):
    def test_grace_ends_after_twenty_minutes(self):
        config = {"boot_notification_grace_minutes": 20}
        self.assertTrue(in_boot_notification_grace(config, 19 * 60))
        self.assertFalse(in_boot_notification_grace(config, 20 * 60))
        self.assertFalse(in_boot_notification_grace({}, 0))

    def test_unnotified_incident_is_sent_if_it_persists_after_grace(self):
        incident = {
            "id": "stream:data_stale", "kind": "data_stale", "profile": "critical",
            "identifier": "stream", "message": "Latest record is stale", "notified_at": None,
        }
        state = {"active": {incident["id"]: incident}}
        with patch("services.service_data_watchdog.notify_admin") as send:
            notify_opened(state, [incident], "live", boot_grace=True)
            send.assert_not_called()
            self.assertIsNone(incident["notified_at"])

            notify_opened(state, [], "live", boot_grace=False)
            send.assert_called_once()
            self.assertIsNotNone(incident["notified_at"])


if __name__ == "__main__":
    unittest.main()
