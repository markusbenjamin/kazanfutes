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
boiler_error_from_power = _diagnostic.boiler_error_from_power
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

    def plug(self, watts, age=0, **updates):
        snapshot = {'timestamp': (self.now - timedelta(seconds=age)).strftime(STAMP_FORMAT),
                    'name': 'boiler_1_plug', 'reachable': True, 'collection_error': None,
                    'measurements': {'power_w': watts}}
        snapshot.update(updates)
        return snapshot

    def write_plugs(self, root, *snapshots):
        path = root / 'data/logs/boilers_power/boiler_plugs.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(snapshot) + '\n' for snapshot in snapshots), encoding='utf-8')
        return path

    def test_power_threshold_includes_zero_and_clears_at_twenty_watts(self):
        for watts, expected in ((0, 'kazán hiba!'), (19.99, 'kazán hiba!'), (20, ''), (68, '')):
            with self.subTest(watts=watts):
                self.assertEqual(boiler_error_from_power(self.switch, self.plug(watts), self.now), expected)

    def test_unavailable_power_is_distinct_from_healthy_power(self):
        for value in (None, '10', True, False, -1, float('nan'), float('inf'), {}, []):
            with self.subTest(value=value):
                self.assertIsNone(boiler_error_from_power(self.switch, self.plug(value), self.now))
        for snapshot in (None, {}, self.plug(10, reachable=False),
                         self.plug(10, collection_error='unavailable'),
                         self.plug(10, measurements=None), self.plug(10, name='boiler_2_plug'),
                         self.plug(10, timestamp='invalid')):
            self.assertIsNone(boiler_error_from_power(self.switch, snapshot, self.now))

    def test_power_freshness_uses_same_limit_as_water(self):
        self.assertEqual(boiler_error_from_power(self.switch, self.plug(10, age=90), self.now), 'kazán hiba!')
        self.assertIsNone(boiler_error_from_power(self.switch, self.plug(10, age=91), self.now))
        self.assertIsNone(boiler_error_from_power(self.switch, self.plug(10, age=-1), self.now))
        for limit in (None, True, '90', 0, -1, float('inf'), float('nan')):
            self.assertIsNone(boiler_error_from_power(self.switch, self.plug(10), self.now, limit))

    def test_power_requires_heating_on_and_an_enabled_circuit(self):
        for switch in (None, {}, {'system': 0, 'cycles': {'1': 1}},
                       {'system': 1, 'cycles': {}}, {'system': 1, 'cycles': {'1': -1}}):
            self.assertEqual(boiler_error_from_power(switch, self.plug(0), self.now), '')
        for mode in (0, 1):
            self.assertEqual(boiler_error_from_power(
                {'system': 1, 'cycles': {'1': mode}}, self.plug(0), self.now), 'kazán hiba!')

    def test_valid_power_overrides_water_and_recovers_on_next_observation(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            _, readings = self.make_files(root)
            for watts, temperature, expected in ((10, 60, 'kazán hiba!'), (20, 22, ''),
                                                  (0, 60, 'kazán hiba!'), (68, 22, '')):
                with self.subTest(watts=watts, temperature=temperature):
                    readings.write_text(json.dumps(self.snapshot({9: temperature})), encoding='utf-8')
                    self.write_plugs(root, self.plug(watts))
                    self.assertEqual(read_boiler_error(root, self.switch, self.now), expected)

    def test_unusable_power_falls_back_to_water_in_both_directions(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            _, readings = self.make_files(root)
            for snapshot in (self.plug(None), self.plug('10'), self.plug(True), self.plug(-1),
                             self.plug(float('nan')), self.plug(10, age=91), self.plug(10, age=-1),
                             self.plug(10, reachable=False), self.plug(10, collection_error='failed'),
                             self.plug(10, timestamp=None), self.plug(10, measurements={})):
                for temperature, expected in ((22, 'kazán hiba!'), (60, '')):
                    self.write_plugs(root, snapshot)
                    readings.write_text(json.dumps(self.snapshot({9: temperature})), encoding='utf-8')
                    self.assertEqual(read_boiler_error(root, self.switch, self.now), expected)

    def test_latest_first_plug_record_wins_and_second_plug_is_ignored(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            _, readings = self.make_files(root)
            readings.write_text(json.dumps(self.snapshot({9: 60})), encoding='utf-8')
            path = self.write_plugs(root, *([self.plug(68)] * 1000), self.plug(10),
                                    self.plug(68, name='boiler_2_plug'))
            with path.open('a', encoding='utf-8') as output:
                output.write('{"timestamp":')
            self.assertEqual(read_boiler_error(root, self.switch, self.now), 'kazán hiba!')
            # A new unreachable/invalid observation must fall back, not reuse the old power.
            for latest in (self.plug(10, reachable=False), self.plug(None)):
                self.write_plugs(root, self.plug(10), latest)
                self.assertEqual(read_boiler_error(root, self.switch, self.now), '')
            self.write_plugs(root, self.plug(0, name='boiler_2_plug'))
            self.assertEqual(read_boiler_error(root, self.switch, self.now), '')

    def test_power_does_not_need_water_readings_or_meter_mapping(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            # Missing water/config files cannot hide an available plug reading.
            for watts, expected in ((10, 'kazán hiba!'), (20, '')):
                self.write_plugs(root, self.plug(watts))
                self.assertEqual(read_boiler_error(root, self.switch, self.now), expected)
            self.write_plugs(root, self.plug(None))
            self.assertEqual(read_boiler_error(root, self.switch, self.now), '')

    def test_missing_or_corrupt_plug_file_uses_water(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            _, readings = self.make_files(root)
            readings.write_text(json.dumps(self.snapshot({9: 22})), encoding='utf-8')
            path = self.write_plugs(root)
            path.write_text('invalid json', encoding='utf-8')
            self.assertEqual(read_boiler_error(root, self.switch, self.now), 'kazán hiba!')
            path.unlink()
            self.assertEqual(read_boiler_error(root, self.switch, self.now), 'kazán hiba!')

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
            self.assertEqual(read_boiler_error('/unused', {'system': 1, 'cycles': {'1': -1}}, self.now), '')


if __name__ == '__main__':
    unittest.main()
