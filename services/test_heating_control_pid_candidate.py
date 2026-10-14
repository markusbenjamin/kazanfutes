"""Offline regression tests; never import or execute either heating service.

Run: python -B -m unittest discover -s services -p test_heating_control_pid_candidate.py
AST extraction excludes project imports, initialization, logs and device I/O.
"""
import ast
import copy
import math
from pathlib import Path
import unittest
from datetime import datetime, timedelta


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'services' / 'heating_control.py'
FMT = '%Y-%m-%d-%H-%M-%S'
NOW = datetime(2026, 2, 9, 15, 4, 53)
GAINS = {'gain_P_lag': '0.4', 'gain_I': '0.00033',
         'gain_P_overshoot': '0', 'gain_D': '0'}


def load_calculations():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    names = {'read_pid_gains', 'calculate_pid_overlay', 'apply_pid_overlay',
             'compare_and_command'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name in names) or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
              t.id.startswith('PID_') for t in n.targets))]
    utils = ast.parse((ROOT / 'utils' / 'project.py').read_text(encoding='utf-8'))
    nodes += [n for n in utils.body if isinstance(n, ast.FunctionDef)
              and n.name == 'logistic_sigmoid']
    env = {'math': math, 'datetime': datetime, 'timedelta': timedelta,
           'settings': {'timestamp_format': FMT}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), env)
    return env


class PIDTests(unittest.TestCase):
    def setUp(self):
        self.env = load_calculations()
        self.gains = self.env['read_pid_gains'](GAINS)

    def state(self, *, integral=0, age=60, temp=20, target=21, sample_age=None):
        if sample_age is None:
            sample_age = age
        return {'version': 2, 'bias_I': integral, 'temp': temp,
                'timestamp': (NOW - timedelta(seconds=age)).strftime(FMT),
                'sensor_timestamp': (NOW - timedelta(seconds=sample_age)).strftime(FMT),
                'set_temp': target, 'gains': list(self.gains.values())}

    def calculate(self, *, previous=None, temp=20, target=21, sample_age=0,
                  valve=10, gains=None, now=NOW):
        return self.env['calculate_pid_overlay'](
            target, temp, (now - timedelta(seconds=sample_age)).strftime(FMT),
            valve, 2, previous, gains or self.gains, now)

    def test_integral_gain_is_independent_of_proportional_gain(self):
        result = self.calculate(previous=self.state())
        self.assertAlmostEqual(result['next_state']['bias_I'], .0198)
        self.assertAlmostEqual(result['setpoint'], 21.4198, places=5)

    def test_legacy_positive_and_negative_integrals_are_discarded(self):
        for value in (-56_000_000, 424562):
            with self.subTest(value=value):
                result = self.calculate(previous={'bias_I': value})
                self.assertEqual(result['next_state']['bias_I'], 0)
                self.assertEqual(result['log']['state']['reset_reason'], 'new_or_legacy_state')
                self.assertLess(result['setpoint'], 21.5)

    def test_invalid_version_two_state_is_discarded(self):
        for value in (-1, 5.01, math.inf, math.nan):
            with self.subTest(value=value):
                result = self.calculate(previous=self.state(integral=value))
                self.assertEqual(result['next_state']['bias_I'], 0)
                self.assertEqual(result['log']['state']['reset_reason'], 'invalid_state')
        for bad in ({'version': 2}, {'version': 2, 'bias_I': 'bad'}, None, []):
            self.assertEqual(self.calculate(previous=bad)['next_state']['bias_I'], 0)

    def test_integral_cannot_wind_down_below_zero(self):
        result = self.calculate(previous=self.state(integral=.001), temp=22)
        self.assertEqual(result['next_state']['bias_I'], 0)
        self.assertEqual(result['setpoint'], 21)

    def test_positive_increment_stops_at_saturation_headroom(self):
        result = self.calculate(previous=self.state(integral=4.59, age=300))
        self.assertAlmostEqual(result['next_state']['bias_I'], 4.6)
        result = self.calculate(previous=self.state(integral=4.8))
        self.assertEqual(result['next_state']['bias_I'], 4.8)
        self.assertLessEqual(result['setpoint'], 26)

    def test_outage_and_backward_clock_do_not_integrate(self):
        for age in (301, 133556, 13885610, -60):
            with self.subTest(age=age):
                result = self.calculate(previous=self.state(integral=4, age=age))
                self.assertEqual(result['next_state']['bias_I'], 0)
                self.assertEqual(result['log']['state']['dt_PID'], 0)

    def test_target_drop_discards_previous_boost(self):
        result = self.calculate(previous=self.state(integral=4, target=22), target=18, temp=20)
        self.assertEqual(result['next_state']['bias_I'], 0)
        self.assertEqual(result['setpoint'], 18)
        self.assertEqual(result['log']['state']['reset_reason'], 'target_reduced')

    def test_setback_does_not_leave_integral_debt_when_heating_resumes(self):
        previous = self.state(integral=0, target=14, temp=20)
        for step in range(60):
            now = NOW + timedelta(minutes=step)
            previous = self.calculate(previous=previous, now=now,
                                      target=14, temp=20)['next_state']
        result = self.calculate(previous=previous, now=NOW + timedelta(hours=1),
                                target=21, temp=20)
        self.assertAlmostEqual(result['next_state']['bias_I'], .0198)
        self.assertGreater(result['setpoint'], 21)

    def test_gain_change_resets_state_and_zero_I_disables_integral(self):
        gains = dict(self.gains, gain_I=0)
        result = self.calculate(previous=self.state(integral=4), gains=gains)
        self.assertEqual(result['next_state']['bias_I'], 0)
        self.assertEqual(result['log']['state']['reset_reason'], 'gains_changed')

    def test_derivative_uses_sensor_interval_and_has_no_setpoint_kick(self):
        gains = dict(self.gains, gain_D=1)
        previous = self.state(temp=21, target=20, sample_age=600)
        previous['gains'] = list(gains.values())
        result = self.calculate(previous=previous, gains=gains, temp=22, target=21)
        self.assertAlmostEqual(result['log']['signals']['heat_rate'], 1 / 600)
        unchanged = self.calculate(previous=previous, gains=gains, temp=21,
                                   target=21, sample_age=600)
        self.assertEqual(unchanged['log']['signals']['heat_rate'], 0)

    def test_sensor_clock_backwards_resets_and_future_sample_keeps_control(self):
        result = self.calculate(previous=self.state(sample_age=0), sample_age=60)
        self.assertEqual(result['log']['state']['reset_reason'], 'sensor_clock_change')
        result = self.calculate(previous=self.state(integral=4), sample_age=-60)
        self.assertEqual(result['log']['state']['reset_reason'], 'invalid_sensor_timestamp')
        self.assertEqual(result['next_state']['bias_I'], 0)
        self.assertAlmostEqual(result['setpoint'], 21.4, places=5)
        self.assertIsNone(result['next_state']['sensor_timestamp'])

    def test_missing_sensor_timestamp_keeps_proportional_control(self):
        for sample in (None, '', 'invalid'):
            result = self.env['calculate_pid_overlay'](
                21, 20, sample, 10, 2, self.state(integral=4), self.gains, NOW)
            self.assertEqual(result['log']['state']['reset_reason'], 'invalid_sensor_timestamp')
            self.assertEqual(result['next_state']['bias_I'], 0)
            self.assertAlmostEqual(result['setpoint'], 21.4, places=5)

    def test_braking_limit_is_enforced_when_gains_enabled(self):
        gains = dict(self.gains, gain_P_overshoot=10, gain_D=1000)
        previous = self.state(temp=21)
        previous['gains'] = list(gains.values())
        result = self.calculate(previous=previous, gains=gains, temp=22)
        self.assertEqual(result['log']['outputs']['bias_overshoot'], -.2)
        self.assertEqual(result['setpoint'], 20.8)

    def test_existing_overshoot_vote_policy_preserved_with_zero_PD(self):
        result = self.calculate(temp=21.3)
        self.assertTrue(result['room_overshoot'])
        self.assertEqual(result['setpoint'], 21)
        self.assertFalse(self.calculate(temp=21.3, valve=2)['room_overshoot'])

    def test_bad_gains_and_nonfinite_inputs_rejected(self):
        for value in ('nan', 'inf', '-1'):
            with self.assertRaises(ValueError):
                self.env['read_pid_gains'](dict(GAINS, gain_I=value))
        for value in (math.nan, math.inf):
            with self.assertRaises(ValueError):
                self.calculate(temp=value)

    def test_february_jump_does_not_reappear_with_correct_gain(self):
        previous = self.state(integral=0, age=61, temp=17.84, target=18.7)
        result = self.calculate(previous=previous, temp=17.84, target=18.7)
        self.assertAlmostEqual(result['next_state']['bias_I'], .00033 * .86 * 61)
        self.assertLess(result['setpoint'], 19.1)

    def test_extended_sequence_remains_bounded(self):
        previous = None
        for step in range(1000):
            now = NOW + timedelta(minutes=step)
            target = 21 if (step // 100) % 2 else 14
            temp = 19 + math.sin(step / 30)
            result = self.calculate(previous=previous, now=now, target=target, temp=temp)
            previous = result['next_state']
            self.assertTrue(0 <= previous['bias_I'] <= 5)
            self.assertTrue(target - .2 <= result['setpoint'] <= target + 5)

    def test_write_failure_discards_state_and_marks_output_unconfirmed(self):
        errors = []
        self.env['ServiceException'] = lambda *a, **kw: errors.append(a)
        for behavior in ('false', 'exception'):
            def write(*a, **kw):
                if behavior == 'exception':
                    raise RuntimeError('offline')
                return False
            self.env['set_thermostat_state_by_id'] = write
            state = {'77': self.state(integral=2)}
            result = self.calculate(previous=state['77'])
            self.assertFalse(self.env['apply_pid_overlay']('77', result, 20, state))
            self.assertNotIn('77', state)
            self.assertIsNone(result['log']['outputs']['set_temp_effective'])
            self.assertFalse(result['log']['command_confirmed'])
        self.assertEqual(len(errors), 2)

    def test_confirmed_write_commits_next_state(self):
        self.env['set_thermostat_state_by_id'] = lambda *a, **kw: True
        self.env['ServiceException'] = lambda *a, **kw: self.fail('Unexpected write error')
        state = {}
        result = self.calculate()
        self.assertTrue(self.env['apply_pid_overlay']('77', result, 20, state))
        self.assertEqual(state['77'], result['next_state'])
        self.assertTrue(result['log']['command_confirmed'])


class ControlIntegrationTests(unittest.TestCase):
    def run_control(self, failed_trv=None, disabled_room=None, state_missing=False,
                    sample_offset=0):
        env = load_calculations()
        logs, errors, writes, saved = [], [], [], {}
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        class Node:
            def write(self, *a, **kw):
                pass
        class ModuleError(Exception):
            pass
        def load_state(path):
            if state_missing:
                raise ModuleError('missing file')
            return {'disabled': {'bias_I': 1}}
        def write(th, **kw):
            writes.append(th)
            return th != failed_trv
        rooms = {r: {'name': r, 'thermostats': str(70 + int(r)), 'cycle': '1'}
                 for r in ('1', '2')}
        config = dict(GAINS, hysteresis_buffer='0.25', demand_hysteresis_open_max='40',
                      demand_hysteresis_open_min='2', demand_hysteresis_close='2',
                      error_max='5', error_min='0.5', temp_data_expiry='60')
        env.update(datetime=Clock, heating_config=config, report=lambda *a, **kw: None,
                   get_rooms_info=lambda: rooms, load_json_to_dict=load_state,
                   room_to_cycle=lambda r: '1', timestamp=lambda t=None: (t or NOW).strftime(FMT),
                   timestamp_to_datetime=lambda t: datetime.strptime(t, FMT),
                   log=logs.append, set_thermostat_state_by_id=write,
                   export_dict_as_json=lambda data, path: saved.update({path: copy.deepcopy(data)}),
                   format_to_decimals=lambda v, n: f'{v:.{n}f}', sign=lambda v: int(v > 0),
                   get_cycles_info=lambda: {str(i): {'name': str(i)} for i in range(1, 5)},
                   system_node=Node(), ModuleException=ModuleError,
                   ServiceException=lambda *a, **kw: errors.append(a),
                   load_commands=lambda *a: [], refresh_commands=lambda *a: None,
                   COMMANDS_PATH='mocked')
        state = {'set_temps': {r: 21 for r in rooms}, 'set_temps_interp': {r: 21 for r in rooms},
                 'measured_temps': {r: 20 for r in rooms},
                 'sensor_last_updated': {r: (NOW + timedelta(seconds=sample_offset)).strftime(FMT)
                                         for r in rooms},
                 'valve_states': {r: [10] for r in rooms}, 'room_states': {r: 0 for r in rooms},
                 'pump_states': {str(i): 0 for i in range(1, 5)}, 'boiler_state': 0,
                 'occupancy': {r: True for r in rooms}}
        switch = {'cycles': {str(i): 0 for i in range(1, 5)},
                  'rooms': {r: -1 if r == disabled_room else 0 for r in rooms}}
        env['compare_and_command'](switch, state)
        return logs, errors, writes, saved

    def test_one_unconfirmed_TRV_does_not_block_other_room(self):
        logs, errors, writes, saved = self.run_control(failed_trv='71')
        self.assertEqual(writes, ['71', '72'])
        self.assertEqual(set(saved['system/PID_state.json']), {'72'})
        self.assertIn({'success_voting': False}, logs)
        self.assertIn({'success_issuing_command': True}, logs)
        self.assertFalse(saved['system/control.json']['pid_commands_confirmed'])
        self.assertEqual(len(errors), 1)

    def test_future_sensor_clock_does_not_interrupt_voting_or_commands(self):
        logs, errors, writes, saved = self.run_control(sample_offset=60)
        self.assertEqual(writes, ['71', '72'])
        self.assertIn({'success_voting': True}, logs)
        self.assertIn({'success_issuing_command': True}, logs)
        self.assertFalse(errors)

    def test_missing_state_starts_clean_and_disabled_history_is_removed(self):
        for missing in (False, True):
            logs, errors, writes, saved = self.run_control(disabled_room='1', state_missing=missing)
            self.assertEqual(writes, ['72'])
            self.assertEqual(set(saved['system/PID_state.json']), {'72'})
            self.assertIn({'success_voting': True}, logs)
            self.assertFalse(errors)

    def test_production_matches_reviewed_candidate(self):
        production = ast.parse((ROOT / 'services' / 'heating_control.py').read_text(encoding='utf-8'))
        candidate = ast.parse((ROOT / 'services' / 'heating_control_pid_candidate.py').read_text(encoding='utf-8'))
        # The production header differs; all executable code must match.
        production.body.pop(0)
        candidate.body.pop(0)
        self.assertEqual(ast.dump(production), ast.dump(candidate))


if __name__ == '__main__':
    unittest.main()
