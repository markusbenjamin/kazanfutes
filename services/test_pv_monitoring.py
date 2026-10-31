"""PV standby must stay quiet without masking logger, connection or inverter faults."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from services import pv_logger as logger
from services import service_data_watchdog as watchdog
from utils.pv_status import no_sunlight_standby, parse_operating_status


NOW = datetime.now(timezone.utc).replace(microsecond=0)
RELATIVE = "electricity/pv_inverter_status.json"
ROOT = Path("/unused")
POLICY = {"max_age_minutes": 15, "source_max_age_minutes": 20, "minimum_dc_voltage_fields": 8}


def native_status(code="40960", label="Standby :  no sunlight"):
    return {
        "success": True,
        "data": [{"status": 1}, {"groupName": "Others", "signals": [{
            "id": 10025, "realValue": code, "value": label, "latestTime": NOW.timestamp(),
        }]}],
    }


def observation(**changes):
    return {
        "timestamp": NOW.isoformat(), "access_state": "reachable", "telemetry_state": "received",
        "source_timestamp": (NOW - timedelta(hours=8)).isoformat(),
        "dc_voltage_state": "all_zero", "dc_voltage_field_count": 8, "active_power_state": "zero",
        **parse_operating_status(native_status(), True), **changes,
    }


def candidates(record, light="", policy=None):
    with patch.object(watchdog, "last_ndjson_record", return_value=record), \
            patch.object(watchdog, "fresh_illuminance_evidence", return_value=light):
        return watchdog.pv_inverter_candidates(ROOT, RELATIVE, ROOT / RELATIVE, policy or POLICY, "critical", NOW)


class OperatingStatusTests(unittest.TestCase):
    def test_native_response_matches_the_device_page(self):
        result = parse_operating_status(native_status(), True)
        self.assertTrue(no_sunlight_standby(result))
        self.assertEqual(result["inverter_operating_state"], "Standby :  no sunlight")
        self.assertEqual(result["inverter_state_source_timestamp"], NOW.isoformat())

    def test_offline_is_not_inferred_to_be_standby(self):
        self.assertEqual(parse_operating_status({}, False), {"inverter_connected": False})
        self.assertFalse(no_sunlight_standby({"inverter_connected": False, "inverter_operating_state_code": 40960}))

    def test_unknown_codes_and_generic_standby_are_not_accepted_as_darkness(self):
        for code in ("0", "768", "99999"):
            self.assertFalse(no_sunlight_standby(parse_operating_status(native_status(code, "Standby"), True)))

    def test_failed_or_missing_operating_status_is_not_normal(self):
        for payload in ({"success": False}, {"success": True, "data": []}, native_status("garbage")):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_operating_status(payload, True)

    @patch.object(logger, "fetch_json")
    def test_connectivity_and_status_are_requested_independently(self, fetch):
        fetch.side_effect = [
            {"status": 200, "json": {"success": True, "data": True}},
            {"status": 200, "json": native_status()},
        ]
        self.assertTrue(no_sunlight_standby(logger.read_inverter_status(object(), "session")))
        self.assertIn("is-device-online?dn=", fetch.call_args_list[0].args[1])
        self.assertIn("device-realtime-data?deviceDn=", fetch.call_args_list[1].args[1])

    @patch.object(logger, "fetch_json")
    def test_offline_device_does_not_reuse_a_cached_standby_reason(self, fetch):
        fetch.return_value = {"status": 200, "json": {"success": True, "data": False}}
        self.assertEqual(logger.read_inverter_status(object(), "session"), {"inverter_connected": False})
        fetch.assert_called_once()

    @patch.object(logger, "fetch_json")
    def test_unavailable_state_endpoint_does_not_silence_monitoring(self, fetch):
        for reply in ({"status": 503, "json": None}, {"status": 200, "json": {"success": False}}):
            fetch.return_value = reply
            with self.assertRaises(logger.PVObservationError):
                logger.read_inverter_status(object(), "session")


class WatchdogPVTests(unittest.TestCase):
    def assert_kind(self, record, kind, **options):
        self.assertEqual([item["kind"] for item in candidates(record, **options)], [kind])

    def test_connected_no_sunlight_standby_allows_stopped_history(self):
        self.assertEqual(candidates(observation()), [])

    def test_connected_no_sunlight_standby_allows_empty_history_after_midnight(self):
        self.assertEqual(candidates(observation(telemetry_state="missing", source_timestamp=None)), [])

    def test_standby_does_not_require_a_weather_station(self):
        self.assertEqual(candidates(observation(), policy={**POLICY, "illumination_evidence": {}}), [])

    def test_bright_light_contradicting_no_sunlight_still_alerts(self):
        self.assert_kind(observation(), "pv_unexpected_standby", light="; fresh WS90 illuminance is 15000 lux")

    def test_missing_diagnostics_still_alert(self):
        self.assert_kind(None, "pv_status_missing")

    def test_stale_or_invalid_diagnostic_timestamp_still_alerts_in_standby(self):
        for stamp in ((NOW - timedelta(minutes=16)).isoformat(), None, "garbage"):
            self.assert_kind(observation(timestamp=stamp), "pv_status_stale")

    def test_cloud_failure_still_alerts_even_with_a_standby_field(self):
        self.assert_kind(observation(access_state="unavailable"), "pv_inverter_unreachable")

    def test_offline_inverter_still_alerts_even_with_a_standby_field(self):
        self.assert_kind(observation(inverter_connected=False), "pv_inverter_disconnected")

    def test_unknown_connectivity_cannot_suppress_stale_production(self):
        self.assert_kind(observation(inverter_connected=None), "pv_inverter_not_reporting")

    def test_old_logger_records_do_not_silently_become_standby(self):
        record = {key: value for key, value in observation().items() if not key.startswith("inverter_")}
        self.assert_kind(record, "pv_inverter_not_reporting")

    def test_fault_is_reported_even_when_history_has_stopped(self):
        self.assert_kind(observation(inverter_operating_state_code=768,
                                    inverter_operating_state="Shutdown: fault"), "pv_inverter_fault")

    def test_running_inverter_with_missing_or_stale_history_still_alerts(self):
        for state in ("received", "missing"):
            self.assert_kind(observation(inverter_operating_state_code=512, telemetry_state=state,
                                        inverter_operating_state="On-grid"), "pv_inverter_not_reporting")

    def test_explicit_zero_voltage_during_operation_still_alerts(self):
        self.assert_kind(observation(inverter_operating_state_code=512, inverter_operating_state="On-grid",
                                    source_timestamp=NOW.isoformat()), "pv_inverter_zero_dc_voltage")

    def test_fresh_nonzero_production_is_healthy(self):
        self.assertEqual(candidates(observation(inverter_operating_state_code=512, inverter_operating_state="On-grid",
                                               source_timestamp=NOW.isoformat(), dc_voltage_state="nonzero",
                                               active_power_state="nonzero")), [])

    def test_invalid_illuminance_is_not_bright_light_evidence(self):
        policy = {"illumination_evidence": {"stream": "weather_station/weather_station.json"}}
        for value in (float("nan"), float("inf"), -1):
            with patch.object(watchdog, "last_ndjson_record", return_value={
                "last_updated": NOW.isoformat(), "state": {"illuminance_lux": value},
            }):
                self.assertEqual(watchdog.fresh_illuminance_evidence(ROOT, policy, NOW), "")


class LoggerHistoryTests(unittest.TestCase):
    @patch.object(logger, "log_observation_status")
    @patch.object(logger, "log_data")
    @patch.object(logger, "read_live_row")
    def test_status_only_observation_does_not_fabricate_a_production_sample(self, read, log, log_status):
        read.return_value = {"timestamp": NOW.isoformat(), "telemetry_state": "missing",
                             **parse_operating_status(native_status(), True)}
        with patch.object(logger, "report"):
            self.assertTrue(logger.main())
        log.assert_not_called()
        status = log_status.call_args.args[0]
        self.assertEqual(status["telemetry_state"], "missing")
        self.assertEqual(status["dc_voltage_state"], "unknown")
        self.assertTrue(no_sunlight_standby(status))

    @patch.object(logger, "log_observation_status")
    @patch.object(logger, "log_data")
    @patch.object(logger, "read_live_row")
    def test_real_production_samples_are_still_logged(self, read, log, log_status):
        read.return_value = {"timestamp": NOW.isoformat(), "source_timestamp": NOW.isoformat(),
                             "active_power_kw": 10, "pv1_input_voltage_v": 500,
                             **parse_operating_status(native_status("512", "On-grid"), True)}
        with patch.object(logger, "report"):
            self.assertTrue(logger.main())
        log.assert_called_once_with(read.return_value, "electricity/pv_inverter.json")
        self.assertEqual(log_status.call_args.args[0]["active_power_state"], "nonzero")

    @patch.object(logger.time, "sleep")
    @patch.object(logger, "post_json", return_value={"status": 200, "json": {"data": []}})
    @patch.object(logger, "fetch_json", return_value={"status": 200, "json": {
        "childList": [{"isSign": True, "mocId": 30014, "nodeName": "Active power(kW)", "unit": "kW"}],
    }})
    @patch.object(logger, "read_inverter_status")
    @patch.object(logger, "extract_roarand_from_performance_logs", return_value="session")
    @patch.object(logger, "make_driver")
    @patch.object(logger, "load_credentials", return_value=("test", "test"))
    @patch.object(logger, "WebDriverWait")
    def test_empty_daily_history_keeps_device_diagnostics(self, wait, credentials, driver_factory, session,
                                                         status, fetch, post, sleep):
        driver = MagicMock()
        driver.find_elements.return_value = []
        driver_factory.return_value = driver
        status.return_value = parse_operating_status(native_status(), True)
        result = logger.read_live_row()
        self.assertTrue(no_sunlight_standby(result))
        self.assertEqual(result["telemetry_state"], "missing")
        self.assertNotIn("source_timestamp", result)
        driver.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
