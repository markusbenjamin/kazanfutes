import ast
import csv
import math
from pathlib import Path
import unittest
from unittest.mock import Mock

from utils.room_environment_formatter import format_room_environment, load_room_environment_sensors

DAY = '2026-10-21'
STAMP = DAY + '-12-00-00'
ROOMS = {'1': {'sensor': 'Aqara4', 'pres': 'Pres5'}, '2': {'sensor': 'Aqara1'}}


def air(stamp=STAMP, co2=600, lux=0):
    return {'timestamp': stamp, 'states': {'nous': {'Nous6': {'co2': co2}, 'Nous3': {'co2': 850}},
            'aqara': {'Aqara3': {'lux': 30}, 'Aqara4': {'lux': lux}, 'Aqara1': {'lux': 15}}}}


class RoomEnvironmentFormatterTests(unittest.TestCase):
    def test_owner_mapping_and_multiple_lux_sources(self):
        result = format_room_environment([air()], [], DAY, ROOMS)
        self.assertEqual(result['1'][0], {'timestamp': STAMP, 'co2': 600, 'lux': 15})
        self.assertEqual(result['2'][0]['co2'], 850)
        self.assertEqual(result['2'][0]['lux'], 15)

    def test_no_number_based_guessing_and_unknowns_are_not_zero(self):
        result = format_room_environment([air()], [], DAY, {'8': {'sensor': 'Sonoff6'}})['8'][0]
        self.assertIsNone(result['co2'])
        self.assertIsNone(result['lux'])

    def test_invalid_air_values_and_real_zero(self):
        for value in [None, True, '10', math.nan, math.inf, -1]:
            result = format_room_environment([air(co2=value, lux=value)], [], DAY, ROOMS)['1'][0]
            self.assertIsNone(result['co2'])
            self.assertEqual(result['lux'], 30)  # Invalid member excluded, not counted as zero.
        self.assertEqual(format_room_environment([air(co2=0, lux=0)], [], DAY, ROOMS)['1'][0]['co2'], 0)

    def test_occupancy_is_evaluated_boolean_and_unknown_remains_null(self):
        controls = [{'timestamp': STAMP, 'occupancy': {'1': False, '2': None}},
                    {'timestamp': DAY+'-12-01-00', 'occupancy': {'1': True}}]
        result = format_room_environment([], controls, DAY, ROOMS)
        self.assertEqual([row['occupancy'] for row in result['1']], [0, 1])
        self.assertEqual([row['occupancy'] for row in result['2']], [None, None])

    def test_malformed_days_order_dedup_and_independent_fields(self):
        result = format_room_environment([air(DAY+'-12-01-00'), air(), air(co2=700), None, {},
            air('2026-10-20-23-59-00')], [{'timestamp': STAMP, 'occupancy': {'1': False}}], DAY, ROOMS)
        self.assertEqual(len(result['1']), 2)
        self.assertEqual(result['1'][0]['co2'], 700)
        self.assertEqual(result['1'][0]['occupancy'], 0)
        self.assertNotIn('occupancy', result['1'][1])

    def test_snapshot_matches_owner_csvs_when_available(self):
        source = Path('dev/db/sept_package/mappings.csv')
        locations = Path('dev/db/sept_package/locations.csv')
        if not source.exists() or not locations.exists():
            self.skipTest('Owner development database is not deployed here')
        with locations.open(encoding='utf-8-sig', newline='') as handle:
            rooms = {row['location_id']: row['legacy_room_number'] for row in csv.DictReader(handle) if row['legacy_room_number']}
        expected = {}
        with source.open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                metric = {'co2_ppm': 'co2', 'illuminance_lux': 'lux'}.get(row['metric'])
                room = rooms.get(row['location_id'])
                if metric and room and row['log_source'].startswith(('nous/', 'aqara/')):
                    expected.setdefault(room, {}).setdefault(metric, []).append(row['log_source'].split('/')[1])
        configured = {room: {metric: sensors for metric, sensors in metrics.items() if sensors}
                      for room, metrics in load_room_environment_sensors().items() if any(metrics.values())}
        self.assertEqual(configured, expected)

    def test_service_exports_all_rooms_even_if_logs_absent(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        section = next(node for node in loop.body if isinstance(node, ast.If)
                       and ast.unparse(node.test) == "'room_environment' in data_types_to_digest")
        outputs = {}
        namespace = {
            'data_types_to_digest': ['room_environment'], 'digestion_daystamp': DAY,
            'log_file_suffix': '', 'export_path_prefix': '',
            'os': Mock(path=Mock(exists=Mock(return_value=False), join=lambda *parts: '/'.join(parts))),
            'get_project_root': lambda: '/unused', 'get_rooms_info': lambda **kw: ROOMS,
            'load_ndjson_to_json_list': Mock(), 'format_room_environment': format_room_environment,
            'export_json_list_to_json_file': lambda data, path: outputs.update({path: data}),
            'report': Mock(), 'log': Mock(), 'ModuleException': RuntimeError, 'ServiceException': Mock()
        }
        exec(compile(ast.Module(body=[section], type_ignores=[]), 'room-formatting', 'exec'), namespace)
        self.assertEqual(outputs, {f'data/formatted/{DAY}/room_{r}_environment.json': [] for r in ROOMS})
        namespace['load_ndjson_to_json_list'].assert_not_called()
        namespace['ServiceException'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
