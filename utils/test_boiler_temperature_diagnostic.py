"""Offline boiler diagnostics: synthetic readings and temporary files only."""
import json
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

# Load the pure helper directly: utils.__init__ imports hardware-facing project.
_spec = importlib.util.spec_from_file_location(
    'boiler_temperature_diagnostic', Path(__file__).with_name('boiler_temperature_diagnostic.py'))
_diagnostic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_diagnostic)
STAMP_FORMAT = _diagnostic.STAMP_FORMAT
boiler_error_from_snapshot = _diagnostic.boiler_error_from_snapshot
read_boiler_error = _diagnostic.read_boiler_error


class BoilerTemperatureTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 12)
        self.switch = {'system': 1, 'cycles': {'1': 0, '2': 1, '3': -1}}
        self.mapping = {'1': 1, '2': 2, '3': 3}

    def snapshot(self, temperatures, age=0):
        return {'timestamp': (self.now - timedelta(seconds=age)).strftime(STAMP_FORMAT),
                'states': {str(meter): {'flow_temperature_c': value}
                           for meter, value in temperatures.items()}}

    def diagnose(self, temperatures, age=0):
        return boiler_error_from_snapshot(self.switch, self.snapshot(temperatures, age),
                                          self.mapping, self.now)

    def test_automatic_and_forced_circuits_count_but_disabled_do_not(self):
        self.assertEqual(self.diagnose({1: 22, 3: 60}), 'kazán hiba!')
        self.assertEqual(self.diagnose({2: 22, 3: 60}), 'kazán hiba!')
        self.assertEqual(self.diagnose({3: 22}), '')

    def test_highest_supply_reading_and_strict_threshold(self):
        for temperatures, expected in [({1: 22, 2: 40}, ''),
                                       ({1: 27.99, 2: 20}, 'kazán hiba!'),
                                       ({1: 28, 2: 20}, '')]:
            with self.subTest(temperatures=temperatures):
                self.assertEqual(self.diagnose(temperatures), expected)

    def test_invalid_values_are_ignored(self):
        for invalid in (None, '20', True, False, float('nan'), float('inf'),
                        float('-inf'), 0, -2, 100, 1000, {}, []):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.diagnose({1: invalid}), '')
                self.assertEqual(self.diagnose({1: invalid, 2: 22}), 'kazán hiba!')
        self.assertEqual(self.diagnose({}), '')

    def test_missing_or_malformed_readings_are_ignored(self):
        for states in ({'1': None}, {'1': {}}, {'1': 20}, None, []):
            snapshot = self.snapshot({})
            snapshot['states'] = states
            self.assertEqual(boiler_error_from_snapshot(
                self.switch, snapshot, self.mapping, self.now), '')

    def test_freshness_boundary_and_future_timestamp(self):
        self.assertEqual(self.diagnose({1: 20}, age=90), 'kazán hiba!')
        self.assertEqual(self.diagnose({1: 20}, age=91), '')
        self.assertEqual(self.diagnose({1: 20}, age=-1), '')
        for stamp in (None, '', 'invalid', 123):
            snapshot = self.snapshot({1: 20})
            snapshot['timestamp'] = stamp
            self.assertEqual(boiler_error_from_snapshot(
                self.switch, snapshot, self.mapping, self.now), '')

    def test_disabled_heating_or_no_enabled_circuits_clears(self):
        for switch in (None, {}, {'system': 0, 'cycles': {'1': 1}},
                       {'system': 1, 'cycles': {}},
                       {'system': 1, 'cycles': {'1': -1}}):
            self.assertEqual(boiler_error_from_snapshot(
                switch, self.snapshot({1: 20}), self.mapping, self.now), '')

    def test_return_temperature_and_pump_state_do_not_affect_diagnostic(self):
        snapshot = self.snapshot({1: 22})
        snapshot['states']['1']['return_temperature_c'] = 60
        for pumps in ({'1': 0}, {'1': 1}, {'1': None}, {}):
            snapshot['pump_states'] = pumps
            self.assertEqual(boiler_error_from_snapshot(
                self.switch, snapshot, self.mapping, self.now), 'kazán hiba!')

    def test_configured_meter_mapping_is_used(self):
        self.assertEqual(boiler_error_from_snapshot(
            self.switch, self.snapshot({1: 60, 9: 22}),
            {'1': 9}, self.now), 'kazán hiba!')

    def test_invalid_freshness_limit_does_not_infer_fault(self):
        for age in (None, '90', True, 0, -1, float('nan'), float('inf')):
            self.assertEqual(boiler_error_from_snapshot(
                self.switch, self.snapshot({1: 22}), self.mapping, self.now, age), '')

    def make_files(self, root):
        config = root / 'config/heating_monitor.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'cycles': {'1': {'meter': 9}},
                                      'reading_max_age_seconds': 90}), encoding='utf-8')
        readings = root / 'data/logs/heat_delivery/heatmeters_state.json'
        readings.parent.mkdir(parents=True)
        return config, readings

    def test_local_snapshot_reading_mapping_recovery_and_missing_data(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            config, readings = self.make_files(root)
            self.assertEqual(read_boiler_error(root, self.switch, self.now), '')
            for temperatures, expected in [({9: 22}, 'kazán hiba!'),
                                           ({9: 28}, ''), ({}, '')]:
                readings.write_text(json.dumps(self.snapshot(temperatures)), encoding='utf-8')
                self.assertEqual(read_boiler_error(root, self.switch, self.now), expected)
            readings.write_text('not json', encoding='utf-8')
            self.assertEqual(read_boiler_error(root, self.switch, self.now), '')
            readings.write_text(json.dumps(self.snapshot({9: 22})), encoding='utf-8')
            config.write_text('{}', encoding='utf-8')
            self.assertEqual(read_boiler_error(root, self.switch, self.now), '')

    def test_latest_snapshot_wins_over_older_warm_readings_and_partial_tail(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            _, readings = self.make_files(root)
            warm = json.dumps(self.snapshot({9: 60}, age=20)) + '\n'
            cold = json.dumps(self.snapshot({9: 22})) + '\n'
            readings.write_text(warm * 1000 + cold + '{"timestamp":', encoding='utf-8')
            self.assertEqual(read_boiler_error(root, self.switch, self.now), 'kazán hiba!')
            # An empty newest snapshot must clear, not reuse the older cold one.
            readings.write_text(cold + json.dumps(self.snapshot({})), encoding='utf-8')
            self.assertEqual(read_boiler_error(root, self.switch, self.now), '')

    def test_heating_off_does_not_read_files(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected read')):
            self.assertEqual(read_boiler_error('/unused', {'system': 0}, self.now), '')


if __name__ == '__main__':
    unittest.main()
