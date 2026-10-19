import ast
import math
from pathlib import Path
import unittest
from unittest.mock import Mock

from utils.external_temperature_formatter import format_ws90_external_temperatures, ws90_external_temperature

DAY = '2026-10-19'


def reading(value=10.2, observed=DAY+'-12-00-00', logged=DAY+'-12-00-05'):
    return {'timestamp': logged, 'last_updated': observed, 'state': {'temperature_c': value}}


def service_try(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    return compile(ast.Module(body=[next(node for node in tree.body if isinstance(node, ast.Try))], type_ignores=[]), path, 'exec')


class ExternalTemperatureFormatterTests(unittest.TestCase):
    def test_temperature_and_zero_and_negatives(self):
        for value in [10.2, 0, -12.5]:
            self.assertEqual(ws90_external_temperature(reading(value)), value)

    def test_invalid_values_are_not_fabricated_as_zero(self):
        for value in [None, True, '10.2', math.nan, math.inf, -math.inf]:
            self.assertIsNone(ws90_external_temperature(reading(value)))
        for entry in [None, {}, {'state': []}, {'external_temp': 99}, reading(observed='bad')]:
            self.assertIsNone(ws90_external_temperature(entry))

    def test_old_and_future_sensor_observations_are_rejected(self):
        self.assertIsNone(ws90_external_temperature(reading(observed=DAY+'-11-54-59')))
        self.assertIsNone(ws90_external_temperature(reading(observed=DAY+'-12-01-00')))

    def test_uses_actual_sensor_timestamps_sorts_and_deduplicates(self):
        entries = [reading(11, DAY+'-12-01-00', DAY+'-12-01-05'), reading(9), reading(10.2),
                   {'timestamp': DAY+'-12-00-00', 'external_temp': 99}]
        self.assertEqual(format_ws90_external_temperatures(entries, DAY), [
            {'timestamp': DAY+'-12-00-00', 'external_temp': 10.2},
            {'timestamp': DAY+'-12-01-00', 'external_temp': 11},
        ])

    def test_day_is_sensor_day_not_logger_day(self):
        self.assertEqual(format_ws90_external_temperatures([
            reading(10, '2026-10-18-23-59-59', DAY+'-00-00-04')], DAY), [])
        self.assertEqual(format_ws90_external_temperatures([], DAY), [])

    def test_formatter_reads_ws90_logs_and_keeps_existing_output_contract(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        section = next(node for node in loop.body if isinstance(node, ast.If) and ast.unparse(node.test) == "'external_temp' in data_types_to_digest")
        for exists, suffix in [(True, ''), (True, '.'+DAY), (False, '')]:
            with self.subTest(exists=exists, suffix=suffix):
                source = Mock(return_value=[reading()])
                export = Mock()
                namespace = {
                    'data_types_to_digest': ['external_temp'], 'digestion_daystamp': DAY,
                    'log_file_suffix': suffix, 'export_path_prefix': '',
                    'os': Mock(path=Mock(exists=Mock(return_value=exists), join=lambda *parts: '/'.join(parts))),
                    'get_project_root': lambda: '/unused', 'load_ndjson_to_json_list': source,
                    'format_ws90_external_temperatures': format_ws90_external_temperatures,
                    'export_json_list_to_json_file': export, 'report': Mock(), 'log': Mock(),
                    'ModuleException': RuntimeError, 'ServiceException': Mock(),
                }
                exec(compile(ast.Module(body=[section], type_ignores=[]), 'external-formatting', 'exec'), namespace)
                if exists:
                    source.assert_called_once_with('data/logs/weather_station/weather_station.json'+suffix)
                else:
                    source.assert_not_called()
                export.assert_called_once_with(
                    [{'timestamp': DAY+'-12-00-00', 'external_temp': 10.2}] if exists else [],
                    'data/formatted/'+DAY+'/external_temp.json')
                namespace['ServiceException'].assert_not_called()

    def test_weather_logger_is_live_publisher_and_reuses_existing_observation(self):
        for value in [10.2, 0, None]:
            with self.subTest(value=value):
                observe, firebase = Mock(return_value=reading(value)), Mock()
                namespace = {
                    'WEATHER_STATION': {'gateway_device': 'gateway', 'ws90_bt_addr': 'test-address'},
                    'SHELLY_CONFIG': {'devices': {'gateway': {}}},
                    'SHELLY_RESOLVER': Mock(resolve_one=Mock(return_value={'ip': 'test-ip'})),
                    'get_weather_station_state': observe, 'log_data': Mock(), 'JSONNodeAtURL': firebase,
                    'ws90_external_temperature': ws90_external_temperature,
                    'ModuleException': RuntimeError, 'ServiceException': Mock(),
                }
                exec(service_try('services/weather_station_logger.py'), namespace)
                observe.assert_called_once_with(shelly_ip='test-ip', ws90_bt_addr='test-address')
                firebase.return_value.write.assert_called_once_with({'external_temp': value}, 'state')
                namespace['log_data'].assert_called_once_with(reading(value), 'weather_station/weather_station.json')
                namespace['ServiceException'].assert_not_called()

    def test_scraper_still_logs_but_cannot_overwrite_firebase(self):
        firebase = Mock()
        namespace = {
            'scrape_external_temperature': Mock(return_value=99), 'JSONNodeAtURL': firebase,
            'log_data': Mock(), 'ModuleException': RuntimeError, 'ServiceException': Mock(),
        }
        exec(service_try('services/external_temp_scraper_and_logger.py'), namespace)
        firebase.assert_not_called()
        namespace['log_data'].assert_called_once_with({'external_temp': 99}, 'external_temp/external_temp.json')
        namespace['ServiceException'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
