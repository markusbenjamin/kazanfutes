"""Offline target-selection regressions; no project imports or device access."""
import ast
import copy
import importlib.util
import math
from pathlib import Path
from datetime import datetime, timedelta
import unittest
from unittest.mock import Mock

import test_heating_control_pid_candidate as control_tests

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 17, 12, 30)
DAY = str((NOW.date() - datetime(1970, 1, 1).date()).days)


def pure_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'utils' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TARGETS = pure_module('heating_targets')
INTERPOLATION = pure_module('set_temperature')


def scheduler_environment(requests=(), cycle_off=False, presence=False, baseline=0, strong=1):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    def timepoint(when=None):
        when = when or NOW
        return {'unix_day': (when.date() - datetime(1970, 1, 1).date()).days,
                'hour_of_day': when.hour, 'day_of_week': when.isoweekday()}
    def update(data, key, value):
        parts = key.split('/')
        for part in parts[:-1]: data = data.setdefault(part, {})
        data[parts[-1]] = value
    env = dict(datetime=Clock, timedelta=timedelta, math=math, copy=copy,
        rooms_info={'1': {'pres': 'sensor', 'cycle': '1'}},
        warming_params={'1': dict(a=100, b=0, start_factor=1, end_factor=1.01, t_min=14, t_max=21, t_off=10)},
        heating_config={'no_presence_offset': '1.5', 'heating_window': '5'},
        export_path_prefix='', local_scheduling_files_relative_path='mocked',
        request_temperature=TARGETS.request_temperature, warming_parameters=TARGETS.warming_parameters,
        cycle_off_requests=TARGETS.cycle_off_requests, cycle_off_mode=TARGETS.cycle_off_mode,
        load_csv_to_2D_array=Mock(return_value=[]), read_request_rows=lambda *a: list(requests),
        select_subtable_from_table=lambda *a, **kw: [],
        response_table_to_dict_list=lambda *a: [dict(cycle='1', date='17/11/2026', hour_of_day='12', duration='2')] if cycle_off else [],
        get_presence_patterns_with_weekly_cycle_weighted_average=lambda *a: baseline,
        datetime_object_from_google_timestamp=lambda value: datetime.strptime(value, '%d/%m/%Y %H:%M:%S'),
        generate_timepoint_info=timepoint, update_nested_dict=update, room_to_cycle=lambda room: '1',
        get_project_root=lambda: '/unused', scrape_external_temperature=Mock(),
        get_scheduling_external_temperature=lambda *a: (10, 'test'),
        get_rooms_occupancy=lambda **kw: {'1': presence}, transpose_dict=lambda value: {'1': {'now': presence}},
        report=Mock(), log=Mock(), ServiceException=Mock(), ModuleException=RuntimeError,
        schedule_update_info={'last_updated': None, 'update_needed': True}, schedule_node=Mock(),
        settings={'timestamp_format': '%Y-%m-%d-%H-%M-%S'},
        request_marker_rows=lambda *a: [[r[k] for k in ('google_timestamp', 'room_id', 'date', 'hour_of_day', 'duration', 'on')] for r in requests])
    source = ROOT / 'services/schedule_and_config_updater.py'
    env['get_rooms_info'] = lambda: env['rooms_info']
    env['load_csv_to_2D_array'] = lambda path: ([['timestamp', 'cycle', 'day', 'hour', 'duration', 'strong'],
        ['17/11/2026 09:00:00', '1', '17/11/2026', '12', '2', str(strong)]]
        if cycle_off and path.endswith('override_cycles.csv') else [])
    names = {'generate_schedule', 'presence_enforcer', 'generate_condensed_schedule', 'update_valid_requests_on_firebase'}
    nodes = [n for n in ast.parse(source.read_text(encoding='utf-8')).body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), env)
    return env


def request(value, start=12, duration=2, submitted='17/11/2026 09:00:00'):
    return dict(room_id='1', date='17/11/2026', hour_of_day=str(start), duration=str(duration),
                on=str(value), google_timestamp=submitted)


class FormTemperatureTests(unittest.TestCase):
    def generate(self, **kwargs):
        env = scheduler_environment(**kwargs)
        result = env['generate_condensed_schedule'](for_how_many_days=2)
        env['ServiceException'].assert_not_called()
        self.assertIsNotNone(result)
        return env, result

    def test_requested_temperature_is_retained_and_setback_applied(self):
        for target in (18, 20.5, 23, 25):
            with self.subTest(target=target):
                _, result = self.generate(requests=[request(target)])
                self.assertEqual(result['requested_temps']['1'][DAY]['12'], target)
                self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], target - 1.5)

    def test_presence_restores_request_not_warming_max(self):
        for target in (10, 18, 23):
            _, result = self.generate(requests=[request(target)], presence=True)
            self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], target)

    def test_lower_request_is_not_clipped_up_to_normal_minimum(self):
        _, result = self.generate(requests=[request(10)])
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 10)

    def test_no_presence_sensor_has_no_absence_reduction(self):
        env = scheduler_environment(requests=[request(23)])
        env['rooms_info']['1']['pres'] = False
        result = env['generate_schedule'](1)
        self.assertEqual(result['schedule']['1'][DAY]['12'], 23)

    def test_latest_request_wins_and_expires(self):
        _, result = self.generate(requests=[request(25), request(18, submitted='17/11/2026 10:00:00')])
        self.assertEqual(result['requested_temps']['1'][DAY]['12'], 18)
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 16.5)
        self.assertEqual(result['condensed_schedule']['1'][DAY]['14'], 14)

    def test_cycle_shutdown_request_retains_precedence(self):
        _, result = self.generate(requests=[request(25)], cycle_off=True, presence=True)
        self.assertEqual(result['requested_temps'], {})
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 10)
        self.assertEqual(result['condensed_schedule']['1'][DAY]['13'], 10)

    def test_timed_off_survives_cached_schedule_and_next_request_preheating(self):
        env, first = self.generate(requests=[request(25, start=14)], cycle_off=True, presence=True)
        result = env['generate_condensed_schedule'](first['presence_with_override'], first['schedule'],
            2, first['requested_temps'], first['cycle_off_modes'])
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 10)
        self.assertEqual(result['condensed_schedule']['1'][DAY]['13'], 10)
        self.assertEqual(result['condensed_schedule']['1'][DAY]['14'], 23.5)

    def test_soft_period_blocks_preheating_but_presence_restores_requested_target(self):
        for presence, expected in ((False, 14), (True, 23)):
            env, result = self.generate(requests=[request(23), request(25, start=14)],
                cycle_off=True, strong=0, presence=presence)
            self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], expected)
            self.assertEqual(result['condensed_schedule']['1'][DAY]['13'], 14)
            env['transpose_dict'] = lambda value: {'1': {'now': False}}
            updated = env['generate_condensed_schedule'](result['presence_with_override'], result['schedule'],
                2, result['requested_temps'], result['cycle_off_modes'])
            self.assertEqual(updated['condensed_schedule']['1'][DAY]['12'], 14)

    def test_soft_presence_without_room_request_restores_warming_max(self):
        _, result = self.generate(cycle_off=True, strong=0, presence=True)
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 21)

    def test_ordinary_schedule_and_presence_keep_their_existing_targets(self):
        for baseline, presence, expected in ((0, False, 14), (1, False, 19.5),
                                             (.5, False, 16), (0, True, 21)):
            _, result = self.generate(baseline=baseline, presence=presence)
            self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], expected)

    def test_cached_schedule_retains_request_when_presence_changes(self):
        env, first = self.generate(requests=[request(23)])
        env['transpose_dict'] = lambda value: {'1': {'now': True}}
        result = env['generate_condensed_schedule'](first['presence_with_override'], first['schedule'],
                                                   2, first['requested_temps'])
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 23)
        env['transpose_dict'] = lambda value: {'1': {'now': False}}
        result = env['generate_condensed_schedule'](result['presence_with_override'], result['schedule'],
                                                   2, result['requested_temps'])
        self.assertEqual(result['condensed_schedule']['1'][DAY]['12'], 21.5)

    def test_upper_request_has_preheating_and_continuous_upward_interpolation(self):
        _, result = self.generate(requests=[request(25)])
        schedule = result['condensed_schedule']['1']
        self.assertTrue(any(14 < schedule[DAY][str(hour)] < 23.5 for hour in range(5, 12)))
        for hour in range(6, 12):
            left = INTERPOLATION.interpolate_set_temperature(schedule, int(DAY), hour, 1 - 1e-8)
            right = INTERPOLATION.interpolate_set_temperature(schedule, int(DAY), hour + 1, 0)
            self.assertAlmostEqual(left, right, places=6)
        self.assertEqual(INTERPOLATION.interpolate_set_temperature(schedule, int(DAY), 14, 0), 14)

    def test_dashboard_request_marker_contains_actual_temperature(self):
        env = scheduler_environment(requests=[request(23.5)])
        env['update_valid_requests_on_firebase']()
        env['ServiceException'].assert_not_called()
        self.assertEqual(env['schedule_node'].write.call_args.args[0]['1'][0]['set_temp'], 23.5)

    def test_invalid_request_does_not_produce_nan_schedule(self):
        for value in ('nan', 'inf', '-inf', 'bad'):
            with self.assertRaises(ValueError): TARGETS.request_temperature(value)


class MasterTemperatureTests(unittest.TestCase):
    def run_control(self, **kwargs):
        return control_tests.ControlIntegrationTests().run_control(**kwargs)

    def test_room_master_selects_max_immediately_and_pid_commands_it(self):
        state = {}
        logs, errors, writes, saved = self.run_control(switch_updates={'rooms': {'1': 1}},
            state_updates={'set_temps': {'1': 14}, 'set_temps_interp': {'1': 14.5}},
            state_transform=lambda current: state.update(reference=current))
        self.assertFalse(errors)
        self.assertEqual(writes, ['71', '72'])
        self.assertEqual(saved['system/PID_state.json']['71']['set_temp'], 23)
        self.assertEqual(state['reference']['set_temps_interp']['1'], 23)
        self.assertEqual(state['reference']['set_temps']['1'], 23)
        self.assertEqual(state['reference']['target_sources']['1'], 'room_master_on')
        self.assertEqual(saved['system/PID_state.json']['72']['set_temp'], 21)

    def test_cycle_master_applies_each_rooms_own_max_including_room_off(self):
        _, errors, writes, saved = self.run_control(switch_updates={'cycles': {'1': 1}, 'rooms': {'1': -1}})
        self.assertFalse(errors)
        self.assertEqual(writes, ['71', '72'])
        self.assertEqual([saved['system/PID_state.json'][th]['set_temp'] for th in ('71', '72')], [23, 24])

    def test_cycle_master_does_not_affect_other_cycles(self):
        _, errors, _, saved = self.run_control(switch_updates={'cycles': {'1': 1}},
                                             room_updates={'2': {'cycle': '2'}})
        self.assertFalse(errors)
        self.assertEqual(saved['system/PID_state.json']['72']['set_temp'], 21)

    def test_master_can_vote_no_above_target(self):
        _, errors, writes, saved = self.run_control(switch_updates={'cycles': {'1': 1}}, temp=25)
        self.assertFalse(errors)
        self.assertEqual(writes, ['71', '72'])
        self.assertEqual(saved['system/control.json']['cycles']['1'], 0)

    def test_schedule_shutdown_still_wins(self):
        _, errors, writes, saved = self.run_control(switch_updates={'cycles': {'1': 1}},
            state_updates={'set_temps': {'1': -1}, 'set_temps_interp': {'1': -1}})
        self.assertFalse(errors)
        self.assertNotIn('71', writes)
        self.assertEqual(saved['system/control.json']['rooms']['1']['vote'], 0)

    def test_cycle_off_overrides_room_on_with_t_off_and_can_heat_below_it(self):
        rows = [['room_id', 'a', 'b', 'start', 'end', 'min', 'max', 't_off'],
                ['1', 100, 0, 1, 1.01, 14, 23, 9], ['2', 100, 0, 1, 1.01, 14, 24, 11]]
        for temperature, vote in ((8, 1), (20, 0)):
            _, errors, writes, saved = self.run_control(temp=temperature,
                switch_updates={'cycles': {'1': -1}, 'rooms': {'1': 1}},
                env_updates={'load_csv_to_2D_array': lambda path: rows if path.endswith('warming_params.csv') else []})
            self.assertFalse(errors)
            self.assertEqual(writes, ['71', '72'])
            self.assertEqual([saved['system/PID_state.json'][th]['set_temp'] for th in ('71', '72')], [9, 11])
            self.assertEqual(saved['system/control.json']['cycles']['1'], vote)

    def test_room_off_defaults_to_t_min_without_new_column(self):
        state = {}
        _, errors, writes, saved = self.run_control(switch_updates={'rooms': {'1': -1}}, temp=13,
            state_transform=lambda current: state.update(reference=current))
        self.assertFalse(errors)
        self.assertEqual(writes, ['71', '72'])
        self.assertEqual(state['reference']['set_temps']['1'], 14)
        self.assertEqual(state['reference']['set_temps_interp']['1'], 14)
        self.assertEqual(state['reference']['target_sources']['1'], 'room_master_off')
        self.assertEqual(saved['system/PID_state.json']['72']['set_temp'], 21)
        self.assertEqual(saved['system/control.json']['rooms']['1']['vote'], 1)

    def test_optional_off_column_accepts_blank_and_omitted_trailing_cells(self):
        header = ['room_id', 'a', 'b', 'start', 'end', 'min', 'max', 't_off']
        for suffix, expected in (([], 14), ([''], 14), (['9.5'], 9.5)):
            result = TARGETS.warming_parameters([header, ['1', 100, 0, 1, 1.01, 14, 23] + suffix], {'1': {}})
            self.assertEqual(result['1']['t_off'], expected)
        with self.assertRaises(ValueError):
            TARGETS.warming_parameters([header, ['1', 100, 0, 1, 1.01, 14, 23, 'nan']], {'1': {}})

    def test_return_to_auto_uses_schedule_again(self):
        self.run_control(switch_updates={'rooms': {'1': 1}})
        _, errors, _, saved = self.run_control()
        self.assertFalse(errors)
        self.assertEqual(saved['system/PID_state.json']['71']['set_temp'], 21)

    def test_master_overrides_even_a_higher_form_target(self):
        _, errors, _, saved = self.run_control(switch_updates={'rooms': {'1': 1}},
            state_updates={'set_temps': {'1': 25}, 'set_temps_interp': {'1': 25}})
        self.assertFalse(errors)
        self.assertEqual(saved['system/PID_state.json']['71']['set_temp'], 23)

    def test_master_does_not_bypass_protective_interlock(self):
        gate = Mock()
        gate.integration_allowed.return_value = False
        gate.prepared_policy = {'inhibit': True, 'generation': 'test'}
        gate.status = {'phase': 'rain_shutdown'}
        gate.decide.return_value = ({str(i): 0 for i in range(1, 5)}, 0)
        _, errors, _, saved = self.run_control(switch_updates={'cycles': {'1': 1}},
                                             env_updates={'rain_interlock': gate})
        self.assertFalse(errors)
        self.assertEqual(saved['system/control.json']['heat_requests']['1'], 1)
        self.assertEqual(saved['system/control.json']['cycles']['1'], 0)
        self.assertEqual(saved['system/control.json']['boiler'], 0)

    def test_master_commands_target_even_without_temperature_feedback(self):
        writer = Mock(return_value=True)
        _, errors, _, saved = self.run_control(switch_updates={'rooms': {'1': 1}},
            state_updates={'measured_temps': {'1': None}, 'sensor_last_updated': {'1': None}},
            env_updates={'set_thermostat_state_by_id': writer})
        self.assertFalse(errors)
        writer.assert_any_call('71', heatsetpoint=23)
        self.assertEqual(saved['system/control.json']['rooms']['1']['vote'], 1)
        self.assertNotIn('71', saved['system/PID_state.json'])

    def test_master_with_missing_valves_still_commands_target_and_checks_temperature(self):
        writer = Mock(return_value=True)
        _, errors, _, saved = self.run_control(switch_updates={'rooms': {'1': 1}}, temp=25,
            state_updates={'valve_states': {'1': None}}, env_updates={'set_thermostat_state_by_id': writer})
        self.assertFalse(errors)
        writer.assert_any_call('71', heatsetpoint=23, externalsensortemp=25)
        self.assertEqual(saved['system/control.json']['rooms']['1']['vote'], 0)

    def test_failed_manual_command_without_feedback_does_not_block_other_rooms(self):
        logs, errors, writes, saved = self.run_control(switch_updates={'cycles': {'1': 1}},
            state_updates={'measured_temps': {'1': None, '2': None}}, failed_trv='71')
        self.assertTrue(errors)
        self.assertEqual(writes, ['71', '72'])
        self.assertFalse(saved['system/control.json']['pid_commands_confirmed'])
        self.assertIn({'success_issuing_command': True}, logs)

    def test_missing_warming_file_keeps_binary_fallback_and_other_rooms(self):
        loader = Mock(side_effect=OSError('missing'))
        _, errors, writes, saved = self.run_control(switch_updates={'rooms': {'1': 1}},
            env_updates={'load_csv_to_2D_array': loader})
        self.assertTrue(errors)
        self.assertEqual(writes, ['72'])
        self.assertEqual(saved['system/control.json']['rooms']['1']['vote'], 1)

    def test_global_off_has_no_master_targets(self):
        self.assertEqual(TARGETS.master_target_rooms({'system': 0}, {'1': {'cycle': '1'}}, {}), {})

    def test_timed_off_overrides_presence_ramp_and_room_on_but_not_other_cycles(self):
        rows = [['timestamp', 'cycle', 'day', 'hour', 'duration', 'strong'],
                ['09/02/2026 09:00:00', '1', '09/02/2026', '15', '1', '1']]
        params = [['room_id', 'a', 'b', 'start', 'end', 'min', 'max', 't_off'],
                  ['1', 100, 0, 1, 1.01, 14, 23, 10], ['2', 100, 0, 1, 1.01, 14, 24, 10]]
        state = {}
        _, errors, writes, saved = self.run_control(switch_updates={'rooms': {'1': 1}},
            room_updates={'2': {'cycle': '2'}},
            env_updates={'load_csv_to_2D_array': lambda path: params if path.endswith('warming_params.csv') else rows},
            state_transform=lambda current: state.update(reference=current))
        self.assertFalse(errors)
        self.assertEqual(writes, ['71', '72'])
        self.assertEqual(saved['system/PID_state.json']['71']['set_temp'], 10)
        self.assertEqual(saved['system/PID_state.json']['72']['set_temp'], 21)
        self.assertEqual(state['reference']['set_temps_interp']['1'], 10)
        self.assertEqual(state['reference']['target_sources']['1'], 'timed_cycle_off')

    def test_timed_off_boundaries_and_persistent_cycle_precedence(self):
        rows = [['timestamp', 'cycle', 'day', 'hour', 'duration', 'strong'],
                ['17/11/2026 09:00:00', '1', '17/11/2026', '23', '2', '1']]
        requests = TARGETS.cycle_off_requests(rows)
        switch = {'system': 1, 'cycles': {'1': 0}, 'rooms': {'1': 1}}
        for now, expected in ((datetime(2026, 11, 17, 22, 59, 59), 0),
                              (datetime(2026, 11, 17, 23), -1),
                              (datetime(2026, 11, 18, 0, 59, 59), -1),
                              (datetime(2026, 11, 18, 1), 0)):
            effective, _, _ = TARGETS.switches_with_timed_off(switch, requests, now)
            self.assertEqual(effective['cycles']['1'], expected)
            self.assertEqual(switch['cycles']['1'], 0)  # Never rewrite the saved switch.
        for mode in (-1, 1):
            switch['cycles']['1'] = mode
            effective, timed, _ = TARGETS.switches_with_timed_off(switch, requests, datetime(2026, 11, 18, 0))
            self.assertEqual(effective['cycles']['1'], mode)
            self.assertEqual(timed, set())

    def test_expired_timed_off_returns_to_automatic_target(self):
        rows = [['timestamp', 'cycle', 'day', 'hour', 'duration'],
                ['09/02/2026 09:00:00', '1', '09/02/2026', '14', '1']]
        _, errors, _, saved = self.run_control(env_updates={'load_csv_to_2D_array': lambda path: rows})
        self.assertFalse(errors)
        self.assertEqual(saved['system/PID_state.json']['71']['set_temp'], 21)

    def test_soft_period_blocks_controller_lookahead_but_keeps_presence_target(self):
        rows = [['timestamp', 'cycle', 'day', 'hour', 'duration', 'strong'],
                ['09/02/2026 09:00:00', '1', '09/02/2026', '15', '1', '0']]
        for nominal in (14, 23):
            state = {}
            _, errors, _, saved = self.run_control(
                state_updates={'set_temps': {'1': nominal}, 'set_temps_interp': {'1': 25}},
                env_updates={'load_csv_to_2D_array': lambda path: rows},
                state_transform=lambda current: state.update(reference=current))
            self.assertFalse(errors)
            self.assertEqual(saved['system/PID_state.json']['71']['set_temp'], nominal)
            self.assertEqual(state['reference']['set_temps_interp']['1'], nominal)
            self.assertEqual(state['reference']['target_sources']['1'], 'timed_cycle_soft')


class CycleFormParsingTests(unittest.TestCase):
    # Exact headings observed in the live response Sheet after the form update.
    headers = ['Timestamp', 'melyik kört?', 'melyik napra? ', 'hány órától?',
               'mennyi időre? (órában)', 'melyik napig?', 'azon belül hány óráig?', 'erős?']

    def test_legacy_duration_and_new_end_dates_can_coexist(self):
        rows = [self.headers,
                ['24/12/2024 15:49:27', '3', '24/12/2024', '0', '84'],
                ['17/11/2026 15:00:00', '1', '18/11/2026', '18', '', '20/11/2026', '8', '1']]
        old, new = TARGETS.cycle_off_requests(rows)
        self.assertEqual(old['end'], datetime(2024, 12, 27, 12))
        self.assertEqual(old['strong'], 0)
        self.assertEqual(new, {'cycle': '1', 'start': datetime(2026, 11, 18, 18),
                               'end': datetime(2026, 11, 20, 8), 'strong': 1})

    def test_new_end_fields_take_precedence_over_legacy_duration(self):
        rows = [self.headers, ['stamp', '1', '18/11/2026', '18', '500', '19/11/2026', '8', '0']]
        self.assertEqual(TARGETS.cycle_off_requests(rows)[0]['end'], datetime(2026, 11, 19, 8))

    def test_header_order_is_not_assumed_for_new_fields(self):
        headers = ['strong', 'end_hour', 'cycle', 'start_date', 'end_date', 'start_hour']
        row = ['1', '8', '2', '18/11/2026', '19/11/2026', '20']
        result = TARGETS.cycle_off_requests([headers, row])[0]
        self.assertEqual(result['cycle'], '2')
        self.assertEqual(result['start'], datetime(2026, 11, 18, 20))
        self.assertEqual(result['end'], datetime(2026, 11, 19, 8))

    def test_overlapping_strong_period_wins_and_releases_back_to_soft(self):
        rows = [self.headers,
                ['stamp', '1', '18/11/2026', '0', '', '20/11/2026', '0', '0'],
                ['stamp', '1', '18/11/2026', '12', '', '18/11/2026', '18', '1']]
        requests = TARGETS.cycle_off_requests(rows)
        for hour, expected in ((11, 0), (12, 1), (17, 1), (18, 0)):
            self.assertEqual(TARGETS.cycle_off_mode(requests, '1', datetime(2026, 11, 18, hour)), expected)
        self.assertIsNone(TARGETS.cycle_off_mode(requests, '1', datetime(2026, 11, 20, 0)))

    def test_blank_strength_is_soft_and_invalid_intervals_are_rejected(self):
        row = ['stamp', '1', '18/11/2026', '8', '', '18/11/2026', '24', '']
        result = TARGETS.cycle_off_requests([self.headers, row])[0]
        self.assertEqual(result['strong'], 0)
        self.assertEqual(result['end'], datetime(2026, 11, 19))
        for index, value in ((6, '7'), (6, ''), (7, '2'), (3, '25')):
            invalid = list(row); invalid[index] = value
            with self.assertRaises(ValueError): TARGETS.cycle_off_requests([self.headers, invalid])


if __name__ == '__main__':
    unittest.main()
