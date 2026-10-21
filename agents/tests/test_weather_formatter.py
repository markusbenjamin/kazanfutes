import ast
import math
from pathlib import Path
import unittest
from unittest.mock import Mock

from utils.external_temperature_formatter import format_ws90_weather

DAY = '2026-10-21'


def reading(**state):
    return {'timestamp': DAY+'-12-00-05', 'last_updated': DAY+'-12-00-00', 'state': state}


class WeatherFormatterTests(unittest.TestCase):
    def test_existing_sensor_fields_and_units_are_preserved(self):
        row = format_ws90_weather([reading(temperature_c=-2, humidity_pct=62, dewpoint_c=-4,
            wind_speed_m_s=2.5, gust_speed_m_s=4, wind_direction_deg=270, illuminance_lux=1234,
            uv_index=1.3, precipitation_mm=1218, rain_status=True, pressure_hpa=997,
            battery_pct=85, battery_voltage_v=5)], DAY)[0]
        self.assertEqual(row['temperature_c'], -2)
        self.assertEqual(row['precipitation_mm'], 1218)  # Cumulative sensor counter, not invented daily rainfall.
        self.assertEqual(row['rain_status'], 1)
        self.assertEqual(row['timestamp'], DAY+'-12-00-00')
        self.assertEqual(len(row), 12)
        self.assertNotIn('battery_pct', row)
        self.assertNotIn('battery_voltage_v', row)

    def test_zero_and_false_are_real_data_missing_is_null(self):
        row = format_ws90_weather([reading(temperature_c=0, illuminance_lux=0, rain_status=False)], DAY)[0]
        self.assertEqual(row['temperature_c'], 0)
        self.assertEqual(row['illuminance_lux'], 0)
        self.assertEqual(row['rain_status'], 0)
        self.assertIsNone(row['humidity_pct'])

    def test_invalid_numeric_values_are_not_coerced(self):
        for value in [None, True, '12', math.nan, math.inf]:
            row = format_ws90_weather([reading(temperature_c=value)], DAY)[0]
            self.assertIsNone(row['temperature_c'])
        row = format_ws90_weather([reading(humidity_pct=101, wind_speed_m_s=-1, wind_direction_deg=361)], DAY)[0]
        self.assertIsNone(row['humidity_pct'])
        self.assertIsNone(row['wind_speed_m_s'])
        self.assertIsNone(row['wind_direction_deg'])

    def test_stale_wrong_day_bad_and_duplicate_observations(self):
        stale = reading(temperature_c=99)
        stale['last_updated'] = DAY+'-11-00-00'
        self.assertEqual(format_ws90_weather([None, {}, stale], DAY), [])
        self.assertEqual(format_ws90_weather([reading(temperature_c=1)], '2026-10-20'), [])
        result = format_ws90_weather([reading(temperature_c=1), reading(temperature_c=2)], DAY)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['temperature_c'], 2)

    def test_service_exports_weather_without_device_io(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        section = next(node for node in loop.body if isinstance(node, ast.If) and ast.unparse(node.test) == "'weather_station' in data_types_to_digest")
        export = Mock()
        namespace = {'data_types_to_digest': ['weather_station'], 'digestion_daystamp': DAY,
            'log_file_suffix': '', 'export_path_prefix': '', 'get_project_root': lambda: '/unused',
            'os': Mock(path=Mock(exists=Mock(return_value=True), join=lambda *p: '/'.join(p))),
            'load_ndjson_to_json_list': Mock(return_value=[reading(temperature_c=0)]),
            'format_ws90_weather': format_ws90_weather, 'export_json_list_to_json_file': export,
            'report': Mock(), 'log': Mock(), 'ModuleException': RuntimeError, 'ServiceException': Mock()}
        exec(compile(ast.Module(body=[section], type_ignores=[]), 'weather-formatting', 'exec'), namespace)
        self.assertEqual(export.call_args.args[0][0]['temperature_c'], 0)
        self.assertEqual(export.call_args.args[1], f'data/formatted/{DAY}/weather_station.json')
        namespace['ServiceException'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
