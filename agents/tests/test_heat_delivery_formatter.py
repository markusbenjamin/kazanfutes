import ast
from datetime import datetime
import math
from pathlib import Path
import unittest
from unittest.mock import Mock

from utils.heat_delivery_formatter import format_cycle_heat_delivery

DAY = '2026-10-21'


def row(minute, power=6000, flow=0.5, meter='1', **extra):
    return {'timestamp': DAY+f'-00-{minute:02d}-00',
            'states': {meter: {'power_w': power, 'volume_flow_m3h': flow, **extra}}}


class HeatDeliveryFormatterTests(unittest.TestCase):
    def test_integrates_watts_into_kwh_and_keeps_flow(self):
        rows = format_cycle_heat_delivery([row(0), row(1), row(2, power=0)], DAY, {'1': 1})['1']
        self.assertEqual([r['energy_kwh'] for r in rows], [0, 0.1, 0.15])
        self.assertEqual([r['flow_m3h'] for r in rows], [0.5]*3)
        self.assertFalse(any(r['energy_partial'] for r in rows))

    def test_uses_explicit_meter_mapping_and_separates_cycles(self):
        result = format_cycle_heat_delivery([row(0, meter='2'), row(1, meter='2')], DAY, {'1': 2, '2': 1})
        self.assertEqual(result['1'][-1]['energy_kwh'], 0.1)
        self.assertIsNone(result['2'][-1]['energy_kwh'])
        self.assertIsNone(result['2'][-1]['flow_m3h'])

    def test_counter_jumps_and_ambiguous_counter_units_are_not_used(self):
        rows = [row(0, energy_kwh=58837000), row(1, energy_kwh=6188000), row(2, energy_kwh=58839000)]
        self.assertEqual(format_cycle_heat_delivery(rows, DAY, {'1': 1})['1'][-1]['energy_kwh'], 0.2)

    def test_invalid_values_are_null_but_real_zero_is_valid(self):
        for value in [None, True, '10', math.nan, math.inf, -1]:
            with self.subTest(value=value):
                result = format_cycle_heat_delivery([row(0, power=value, flow=value)], DAY, {'1': 1})['1'][0]
                self.assertIsNone(result['energy_kwh'])
                self.assertIsNone(result['flow_m3h'])
        result = format_cycle_heat_delivery([row(0, power=0, flow=0)], DAY, {'1': 1})['1'][0]
        self.assertEqual((result['energy_kwh'], result['flow_m3h']), (0, 0))

    def test_does_not_integrate_across_long_or_invalid_gaps(self):
        rows = format_cycle_heat_delivery([row(0), row(1), row(5), row(6)], DAY, {'1': 1})['1']
        self.assertEqual([r['energy_kwh'] for r in rows], [0, 0.1, 0.1, 0.2])
        self.assertTrue(rows[-1]['energy_partial'])
        rows = format_cycle_heat_delivery([row(0), row(1, power=None), row(2), row(3)], DAY, {'1': 1})['1']
        self.assertEqual([r['energy_kwh'] for r in rows], [0, None, 0, 0.1])
        self.assertTrue(rows[-1]['energy_partial'])

    def test_sorts_deduplicates_and_filters_day(self):
        result = format_cycle_heat_delivery([row(1), row(0), row(1, power=0), None, {},
            {'timestamp': 'bad', 'states': {}}, {'timestamp': '2026-10-20-23-59-59', 'states': {}}], DAY, {'1': 1})['1']
        self.assertEqual([r['energy_kwh'] for r in result], [0, 0.05])
        self.assertEqual(format_cycle_heat_delivery([], DAY, {'1': 1}), {'1': []})

    def test_late_first_observation_marks_energy_partial(self):
        result = format_cycle_heat_delivery([row(10)], DAY, {'1': 1})['1'][0]
        self.assertTrue(result['energy_partial'])

    def test_formatter_writes_all_four_files_without_device_io(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        section = next(node for node in loop.body if isinstance(node, ast.If)
                       and ast.unparse(node.test) == "'cycle_heat_delivery' in data_types_to_digest")
        for exists in [False, True]:
            with self.subTest(exists=exists):
                outputs = {}
                namespace = {
                    'data_types_to_digest': ['cycle_heat_delivery'], 'digestion_daystamp': DAY,
                    'log_file_suffix': '', 'export_path_prefix': '',
                    'os': Mock(path=Mock(exists=Mock(return_value=exists), join=lambda *parts: '/'.join(parts))),
                    'get_project_root': lambda: '/unused', 'load_ndjson_to_json_list': Mock(return_value=[row(0)]),
                    'load_json_to_dict': Mock(return_value={'cycles': {str(c): {'meter': c} for c in range(1, 5)}}),
                    'format_cycle_heat_delivery': format_cycle_heat_delivery,
                    'export_json_list_to_json_file': lambda data, path: outputs.update({path: data}),
                    'report': Mock(), 'log': Mock(), 'ModuleException': RuntimeError, 'ServiceException': Mock(),
                }
                exec(compile(ast.Module(body=[section], type_ignores=[]), 'heat-formatting', 'exec'), namespace)
                self.assertEqual(len(outputs), 4)
                self.assertIn('data/formatted/'+DAY+'/cycle_1_heat_delivery.json', outputs)
                if not exists:
                    self.assertTrue(all(rows == [] for rows in outputs.values()))
                    namespace['load_ndjson_to_json_list'].assert_not_called()
                namespace['ServiceException'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
