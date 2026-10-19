import ast
from datetime import datetime
import math
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from utils.boiler_power_formatter import boiler_power_snapshot, format_boiler_power, format_boiler_commands

DAY = '2026-10-18'


def reading(name='boiler_1_plug', power=0, reachable=True, stamp=DAY+'-12-00-00'):
    return {'name': name, 'timestamp': stamp, 'reachable': reachable, 'measurements': {'power_w': power}}


def command(setting, stamp, executed=True, device='boiler'):
    return {'device': device, 'setting': setting, 'executed': executed, 'execution_timestamp': stamp}


class BoilerPowerFormatterTests(unittest.TestCase):
    def test_keeps_devices_separate_and_real_zero(self):
        result = format_boiler_power([reading(power=0), reading('boiler_2_plug', 125.5)], DAY)
        self.assertEqual(result['boiler_1_plug'][0]['power_w'], 0)
        self.assertEqual(result['boiler_2_plug'][0]['power_w'], 125.5)

    def test_uncommissioned_devices_have_empty_series(self):
        self.assertEqual(format_boiler_power([], DAY), {'boiler_1_plug': [], 'boiler_2_plug': []})

    def test_unavailable_invalid_readings_are_explicit_gaps(self):
        for value in [None, True, '25', math.nan, math.inf, -1]:
            with self.subTest(value=value):
                self.assertIsNone(format_boiler_power([reading(power=value)], DAY)['boiler_1_plug'][0]['power_w'])
        self.assertIsNone(format_boiler_power([reading(power=100, reachable=False)], DAY)['boiler_1_plug'][0]['power_w'])

    def test_filters_day_sorts_and_uses_latest_duplicate(self):
        rows = [reading(power=20, stamp=DAY+'-12-01-00'), reading(power=10),
                reading(power=30, stamp=DAY+'-12-01-00'), reading(stamp='2026-10-17-12-00-00'),
                reading(name='other_plug'), None, {}]
        self.assertEqual([r['power_w'] for r in format_boiler_power(rows, DAY)['boiler_1_plug']], [10, 30])

    def test_live_snapshot_clears_unavailable_and_omitted_devices(self):
        devices = [{'name': 'boiler_1_plug', 'facts': {'reachable': True, 'measurements': {'power_w': 0}}},
                   {'name': 'boiler_2_plug', 'facts': {'reachable': False, 'measurements': {'power_w': 100}}}]
        snapshot = boiler_power_snapshot(devices, DAY+'-12-00-00')
        self.assertEqual(snapshot['boiler_1_plug']['power_w'], 0)
        self.assertIsNone(snapshot['boiler_2_plug']['power_w'])
        self.assertIsNone(boiler_power_snapshot([], DAY+'-12-00-00')['boiler_1_plug']['power_w'])

    def test_commands_carry_prior_state_and_only_use_executed_boiler_commands(self):
        rows = [command(1, '2026-10-17-23-00-00'), command(0, DAY+'-10-00-00'),
                command(1, DAY+'-11-00-00', executed=False), command(1, DAY+'-12-00-00', device='pump_1'),
                command(1, DAY+'-18-00-00')]
        result = format_boiler_commands(rows, DAY, datetime(2026, 10, 18, 15))
        self.assertEqual(result, [
            {'timestamp': DAY+'-00-00-00', 'command_on': 1},
            {'timestamp': DAY+'-10-00-00', 'command_on': 0},
            {'timestamp': DAY+'-15-00-00', 'command_on': 0},
        ])

    def test_unknown_history_is_not_assumed_off(self):
        self.assertEqual(format_boiler_commands([], DAY, datetime(2026, 10, 18, 15)), [])
        result = format_boiler_commands([command(1, DAY+'-12-00-00')], DAY, datetime(2026, 10, 18, 15))
        self.assertEqual(result[0], {'timestamp': DAY+'-12-00-00', 'command_on': 1})

    def test_previous_on_is_extended_to_end_of_past_day(self):
        result = format_boiler_commands([command(1, '2026-10-17-23-00-00')], DAY, datetime(2026, 10, 19))
        self.assertEqual(result[-1], {'timestamp': DAY+'-23-59-59', 'command_on': 1})

    def test_formatter_missing_sources_exports_empty_files_without_error(self):
        tree = ast.parse(Path('services/data_formatter.py').read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For))
        section = next(node for node in loop.body if isinstance(node, ast.If) and "'boilers_power'" in ast.unparse(node.test))
        outputs = {}
        namespace = {
            'data_types_to_digest': ['boilers_power'], 'digestion_daystamp': DAY,
            'log_file_suffix': '', 'export_path_prefix': '',
            'os': Mock(path=Mock(exists=Mock(return_value=False), join=lambda *parts: '/'.join(parts))),
            'get_project_root': lambda: '/unused',
            'format_boiler_power': format_boiler_power, 'format_boiler_commands': format_boiler_commands,
            'export_json_list_to_json_file': lambda data, path: outputs.update({path: data}),
            'report': Mock(), 'log': Mock(), 'ServiceException': Mock(), 'ModuleException': RuntimeError,
        }
        exec(compile(ast.Module(body=[section], type_ignores=[]), 'boiler-formatting', 'exec'), namespace)
        self.assertEqual(len(outputs), 3)
        self.assertTrue(all(value == [] for value in outputs.values()))
        namespace['ServiceException'].assert_not_called()

    def test_monitor_publishes_existing_reading_and_dry_run_does_not_write(self):
        from services import boiler_power_monitor as monitor
        for dry_run in [False, True]:
            with self.subTest(dry_run=dry_run), patch.object(monitor, 'run', return_value={'devices': []}) as collect, \
                    patch.object(monitor, 'read_json', return_value={}), \
                    patch.object(monitor, 'JSONNodeAtURL') as node, \
                    patch('sys.argv', ['boiler_power_monitor.py'] + (['--dry-run'] if dry_run else [])):
                self.assertEqual(monitor.main(), 0)
                collect.assert_called_once_with({}, dry_run=dry_run, boiler_only=True)
                if dry_run:
                    node.assert_not_called()
                else:
                    self.assertEqual(node.return_value.write.call_args.args[1], 'state/boiler_plugs')


if __name__ == '__main__':
    unittest.main()
