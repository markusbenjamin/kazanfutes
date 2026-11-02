"""Station freshness and web fallback for heating schedule generation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from utils.scheduling_temperature import get_scheduling_external_temperature


NOW = datetime(2026, 11, 2, 20, 40)
STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'


def reading(value=7.9, *, observed=None, logged=None):
    observed = observed if observed is not None else NOW - timedelta(seconds=10)
    logged = logged if logged is not None else NOW - timedelta(seconds=5)
    return {
        'timestamp': logged.strftime(STAMP_FORMAT),
        'last_updated': observed.strftime(STAMP_FORMAT),
        'state': {'temperature_c': value},
    }


class SchedulingTemperatureTests(unittest.TestCase):
    def select(self, record, fallback=None, *, now=NOW):
        fallback = fallback if fallback is not None else Mock(return_value=8.7)
        with patch('utils.scheduling_temperature.last_ndjson_record', return_value=record) as load:
            result = get_scheduling_external_temperature('/project', fallback, now=now)
        load.assert_called_once_with(str(Path('/project') / 'data/logs/weather_station/weather_station.json'))
        return result, fallback

    def test_fresh_station_prevents_web_request_including_zero_and_negative(self):
        for value in (7.9, 0, -12.5):
            with self.subTest(value=value):
                result, fallback = self.select(reading(value))
                self.assertEqual(result, (value, 'WS90'))
                fallback.assert_not_called()

    def test_missing_log_uses_web(self):
        with tempfile.TemporaryDirectory() as root:
            fallback = Mock(return_value=8.7)
            self.assertEqual(get_scheduling_external_temperature(root, fallback, now=NOW), (8.7, 'Open-Meteo'))
            fallback.assert_called_once_with()

    def test_invalid_station_records_use_web(self):
        records = [None, {}, {'state': []}, reading(None), reading(True), reading('7.9'),
                   reading(float('nan')), reading(float('inf')), reading(float('-inf')),
                   {**reading(), 'last_updated': 'invalid'}, {**reading(), 'timestamp': 'invalid'}]
        for record in records:
            with self.subTest(record=record):
                result, fallback = self.select(record)
                self.assertEqual(result, (8.7, 'Open-Meteo'))
                fallback.assert_called_once_with()

    def test_stale_sensor_is_rejected_even_when_logger_is_current(self):
        record = reading(observed=NOW - timedelta(minutes=6), logged=NOW)
        result, fallback = self.select(record)
        self.assertEqual(result, (8.7, 'Open-Meteo'))
        fallback.assert_called_once_with()

    def test_stopped_logger_cannot_make_old_sensor_data_look_fresh(self):
        old = NOW - timedelta(hours=2)
        result, fallback = self.select(reading(observed=old, logged=old))
        self.assertEqual(result, (8.7, 'Open-Meteo'))
        fallback.assert_called_once_with()

    def test_wall_clock_freshness_and_future_tolerance_boundaries(self):
        for seconds, source in ((300, 'WS90'), (301, 'Open-Meteo'), (-30, 'WS90'), (-31, 'Open-Meteo')):
            with self.subTest(age=seconds):
                observed = NOW - timedelta(seconds=seconds)
                result, fallback = self.select(reading(observed=observed, logged=observed))
                self.assertEqual(result[1], source)
                self.assertEqual(fallback.call_count, int(source == 'Open-Meteo'))

    def test_future_sensor_timestamp_relative_to_logger_uses_web(self):
        result, fallback = self.select(reading(observed=NOW, logged=NOW - timedelta(minutes=1)))
        self.assertEqual(result, (8.7, 'Open-Meteo'))
        fallback.assert_called_once_with()

    def test_timezone_aware_now_is_compared_with_local_sensor_time(self):
        result, fallback = self.select(reading(), now=NOW.astimezone(timezone.utc))
        self.assertEqual(result, (7.9, 'WS90'))
        fallback.assert_not_called()

    def test_fresh_reading_from_previous_day_is_usable_after_midnight(self):
        now = NOW.replace(hour=0, minute=1)
        observed = now - timedelta(minutes=2)
        result, fallback = self.select(reading(observed=observed, logged=observed), now=now)
        self.assertEqual(result, (7.9, 'WS90'))
        fallback.assert_not_called()

    def test_zero_and_negative_web_temperatures_are_preserved(self):
        for value in (0, -12.5):
            with self.subTest(value=value):
                result, fallback = self.select(None, Mock(return_value=value))
                self.assertEqual(result, (value, 'Open-Meteo'))
                fallback.assert_called_once_with()

    def test_invalid_web_temperature_is_not_used_for_heating(self):
        for value in (None, True, '8.7', float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'Open-Meteo'):
                    self.select(None, Mock(return_value=value))

    def test_web_failure_propagates_if_station_is_unavailable(self):
        with self.assertRaisesRegex(RuntimeError, 'network unavailable'):
            self.select(None, Mock(side_effect=RuntimeError('network unavailable')))


if __name__ == '__main__':
    unittest.main()
