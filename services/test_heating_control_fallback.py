"""Failure-path tests with extracted controller functions and mocked device I/O."""
import copy
import math
import unittest
from datetime import timedelta
from unittest.mock import Mock

import test_heating_control_pid_candidate as control_tests
from test_heating_control_pid_candidate import load_calculations, NOW, FMT


class FallbackTests(unittest.TestCase):
    def run_control(self, **kwargs):
        return control_tests.ControlIntegrationTests().run_control(**kwargs)

    @staticmethod
    def remove_inputs(state):
        for field in ('measured_temps', 'sensor_last_updated', 'occupancy', 'valve_states',
                      'room_states', 'pump_states', 'boiler_state'):
            state.pop(field, None)

    def test_all_inputs_missing_still_commands_every_cycle_from_binary_votes(self):
        logs, errors, writes, saved = self.run_control(
            room_updates={'2': {'cycle': '4'}}, state_transform=self.remove_inputs,
            state_updates={'set_temps': {'1': 14}, 'set_temps_interp': {'1': 14}})
        control = saved['system/control.json']
        self.assertEqual(control['rooms'], {'1': {'vote': 0, 'reason': 't_off'},
                                           '2': {'vote': 1, 'reason': 't_on'}})
        self.assertEqual(control['cycles'], {'1': 0, '2': 0, '3': 0, '4': 1})
        self.assertEqual(control['boiler'], 1)
        for device, setting in [('pump_1', 0), ('pump_2', 0), ('pump_3', 0), ('pump_4', 1), ('boiler', 1)]:
            self.assertIn({'command_issuance': {'device': device, 'state': setting}}, logs)
        self.assertIn({'success_voting': True}, logs)
        self.assertIn({'success_issuing_command': True}, logs)
        self.assertEqual(writes, [])
        self.assertFalse(errors)

    def test_manual_switches_work_without_sensor_inputs(self):
        for switches, target, vote, reason in (
                ({'cycles': {'1': 1}}, 14, 1, 'c_m_on'),
                ({'cycles': {'1': -1}}, 21, 0, 'c_m_off'),
                ({'rooms': {'1': 1}}, 14, 1, 'r_m_on'),
                ({'rooms': {'1': -1}}, 21, 0, 'r_m_off'),
                ({'cycles': {'1': 1}}, -1, 0, 'c_s_m_off')):
            with self.subTest(switches=switches, target=target):
                logs, errors, writes, saved = self.run_control(
                    switch_updates=switches, state_transform=self.remove_inputs,
                    state_updates={'set_temps': {'1': target}, 'set_temps_interp': {'1': target}})
                self.assertEqual(saved['system/control.json']['rooms']['1'], {'vote': vote, 'reason': reason})
                self.assertFalse(errors)

    def test_missing_valves_uses_temperature_control_without_TRV_writes(self):
        for valves in (None, [], [None], [math.nan], [101], [-1], 'invalid', [10, None]):
            for temp, vote in ((19, 1), (23, 0)):
                with self.subTest(valves=valves, temp=temp):
                    logs, errors, writes, saved = self.run_control(state_updates={
                        'valve_states': {'1': valves}, 'measured_temps': {'1': temp}})
                    self.assertEqual(saved['system/control.json']['rooms']['1']['vote'], vote)
                    self.assertEqual(writes, ['72'])
                    self.assertIn({'success_issuing_command': True}, logs)
                    self.assertFalse(errors)

    def test_invalid_temperatures_and_timestamps_use_binary_control(self):
        for temp, stamp in ((math.nan, NOW.strftime(FMT)), (math.inf, NOW.strftime(FMT)),
                            ('bad', NOW.strftime(FMT)), (True, NOW.strftime(FMT)), (20, 'bad')):
            with self.subTest(temp=temp, stamp=stamp):
                logs, errors, writes, saved = self.run_control(state_updates={
                    'measured_temps': {'1': temp}, 'sensor_last_updated': {'1': stamp}})
                self.assertEqual(saved['system/control.json']['rooms']['1'], {'vote': 1, 'reason': 't_on'})
                self.assertEqual(writes, ['72'])
                self.assertFalse(errors)

    def test_missing_occupancy_and_previous_votes_do_not_block_control(self):
        def remove(state):
            state.pop('occupancy')
            state.pop('room_states')
        logs, errors, writes, saved = self.run_control(state_transform=remove, valve=2, temp=21.1)
        self.assertEqual(saved['system/control.json']['rooms']['1'], {'vote': 1, 'reason': 'd_h_on'})
        self.assertEqual(writes, ['71', '72'])
        self.assertIn({'success_voting': True}, logs)
        self.assertFalse(errors)

    def test_one_room_calculation_error_keeps_its_base_vote_and_continues(self):
        original = load_calculations()['calculate_pid_overlay']
        def calculate(*args):
            if args[1] == 19:
                raise RuntimeError('simulated room failure')
            return original(*args)
        logs, errors, writes, saved = self.run_control(
            state_updates={'measured_temps': {'1': 19}},
            env_updates={'calculate_pid_overlay': calculate})
        self.assertEqual(saved['system/control.json']['rooms']['1'], {'vote': 1, 'reason': 't_on'})
        self.assertEqual(saved['system/control.json']['rooms']['2'], {'vote': 1, 'reason': 'd_high'})
        self.assertIn({'success_voting': False}, logs)
        self.assertIn({'success_issuing_command': True}, logs)
        self.assertEqual(writes, ['72'])
        self.assertEqual(len(errors), 1)

    def test_obsolete_failed_command_is_cancelled_even_if_pump_already_matches(self):
        old = {'device': 'pump_1', 'setting': 1, 'executed': False,
               'issuance_timestamp': (NOW - timedelta(minutes=2)).strftime(FMT),
               'due_timestamp': (NOW - timedelta(minutes=2)).strftime(FMT)}
        queued = Mock()
        logs, errors, writes, saved = self.run_control(temp=23, env_updates={
            'load_commands': lambda *a: [old], 'refresh_commands': queued})
        self.assertEqual(saved['system/control.json']['cycles']['1'], 0)
        queued.assert_called_once_with([])
        self.assertFalse(errors)

    def test_opposite_command_replaces_failed_command_when_pump_state_unknown(self):
        old = {'device': 'pump_1', 'setting': 1, 'executed': False,
               'issuance_timestamp': (NOW - timedelta(minutes=2)).strftime(FMT),
               'due_timestamp': (NOW - timedelta(minutes=2)).strftime(FMT)}
        queued = Mock()
        logs, errors, writes, saved = self.run_control(temp=23,
            state_updates={'pump_states': {'1': None}},
            env_updates={'load_commands': lambda *a: [old], 'refresh_commands': queued})
        commands = queued.call_args.args[0]
        self.assertEqual([(c['device'], c['setting']) for c in commands], [('pump_1', 0)])
        self.assertFalse(errors)


class AcquisitionTests(unittest.TestCase):
    def environment(self):
        env = load_calculations()
        class Node:
            def write(self, *a, **kw): pass
        class ModuleError(Exception): pass
        rooms = {'1': {'thermostats': '71;72'}, '2': {'thermostats': '73'}}
        reading = {'temp': 2000, 'hum': None, 'last_updated': NOW.strftime(FMT),
                   'thermostat_temp': None, 'thermostat_last_updated': None}
        env.update(rooms=rooms, condensed_schedule={r: {'1': {'0': 21}} for r in rooms},
            report=Mock(), log=Mock(), ModuleException=ModuleError, ServiceException=Mock(),
            system_node=Node(), timestamp=lambda: NOW.strftime(FMT),
            get_room_temps_and_humidity=Mock(return_value={r: dict(reading) for r in rooms}),
            get_rooms_occupancy=Mock(return_value=dict.fromkeys(rooms, False)),
            generate_timepoint_info=lambda: {'unix_day': 1, 'hour_of_day': 0},
            load_json_to_dict=Mock(return_value={'room_states': dict.fromkeys(rooms, 0)}),
            schedule_with_recent_history=lambda schedule, *a: (schedule, {}),
            interpolate_set_temperature=lambda *a: 21,
            get_thermostat_state_by_id=Mock(return_value={'valve': 10}),
            get_pump_state=Mock(return_value=1), get_boiler_state=Mock(return_value=1))
        return env

    def test_total_read_failure_returns_complete_unknown_state(self):
        env = self.environment()
        for name in ('get_room_temps_and_humidity', 'get_rooms_occupancy',
                     'get_thermostat_state_by_id', 'get_pump_state', 'get_boiler_state', 'load_json_to_dict'):
            env[name].side_effect = env['ModuleException']('unavailable')
        state = env['get_system_state']()
        for field in ('measured_temps', 'sensor_last_updated', 'occupancy', 'room_states'):
            self.assertEqual(state[field], {'1': None, '2': None})
        self.assertEqual(state['valve_states'], {'1': [None, None], '2': [None]})
        self.assertEqual(state['pump_states'], dict.fromkeys(('1', '2', '3', '4')))
        self.assertIsNone(state['boiler_state'])
        self.assertEqual(state['set_temps'], {'1': 21, '2': 21})

    def test_one_failed_valve_and_pump_preserve_other_readings(self):
        env = self.environment()
        def valve(th, *a):
            if th == '72': raise RuntimeError('offline')
            return {'valve': 10}
        def pump(cycle):
            if cycle == '2': raise RuntimeError('offline')
            return 1
        env.update(get_thermostat_state_by_id=valve, get_pump_state=pump)
        state = env['get_system_state']()
        self.assertEqual(state['valve_states'], {'1': [10, None], '2': [10]})
        self.assertEqual(state['pump_states'], {'1': 1, '2': None, '3': 1, '4': 1})
        self.assertEqual(state['measured_temps'], {'1': 20, '2': 20})


class ExecutionTests(unittest.TestCase):
    def test_failed_pump_does_not_block_other_pumps_or_boiler_and_is_retained(self):
        for failure in ('exception', 'unconfirmed'):
            with self.subTest(failure=failure):
                env = load_calculations()
                commands = [{'device': device, 'setting': 1, 'executed': False,
                    'issuance_timestamp': '2020-01-01-00-00-00',
                    'due_timestamp': '2020-01-01-00-00-00', 'execution_timestamp': None}
                    for device in ('pump_1', 'pump_2', 'pump_3', 'pump_4', 'boiler')]
                calls = []
                def pump(cycle, setting):
                    calls.append(cycle)
                    if cycle == '1':
                        if failure == 'exception': raise RuntimeError('offline')
                        return False
                    return True
                env.update(report=Mock(), log=Mock(), ServiceException=Mock(), ModuleException=RuntimeError,
                    system_node=Mock(), load_commands=lambda *a: copy.deepcopy(commands), COMMANDS_PATH='mock',
                    timestamp_to_datetime=lambda t: env['datetime'].strptime(t, FMT),
                    timestamp=lambda: NOW.strftime(FMT), system_state={}, set_pump_state=pump,
                    set_boiler_state=Mock(return_value=True), refresh_commands=Mock(), archive_commands=Mock())
                env['execute_commands']()
                self.assertEqual(calls, ['1', '2', '3', '4'])
                env['set_boiler_state'].assert_called_once_with(1)
                self.assertEqual([c['device'] for c in env['refresh_commands'].call_args.args[0]], ['pump_1'])
                self.assertEqual(len(env['archive_commands'].call_args.args[0]), 4)
                self.assertIsNone(env['system_state']['pump_states']['1'])
                env['log'].assert_called_with({'success_executing_commands': False})


if __name__ == '__main__':
    unittest.main()
