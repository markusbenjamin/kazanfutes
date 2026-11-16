"""Offline rain/heating safety tests. All device operations use fake relays/GPIO."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services import shelly_plug_manager as manager
from utils.heating_rain_interlock import (
    CYCLES, DEFAULTS, HeatingRainInterlock, acknowledgement_valid, coordinate,
    finish_restoration, policy_from_state, residual_decisions, water_readings,
)
from utils.rain_plug_control import initial_state, off_expected

NOW = 1794826800.0
OPTIONS = dict(DEFAULTS, enabled=True)
NORMAL = {'version': 1, 'inhibit': False, 'phase': 'normal', 'generation': None, 'restored_at': None}
RAIN = dict(NORMAL, inhibit=True, phase='rain_shutdown', generation='rain-episode')
CONFIG = {'heating_interlock': OPTIONS, 'plugs': {'one': {'optional_until_seen': False}}}
SHELLY = {'devices': {'one': {'mac': '00:11:22:33:44:55'}}}


def water(temp=60, now=NOW):
    return {c: {'supply_c': temp, 'observed_at': now, 'fresh': temp is not None} for c in CYCLES}


def policy_state(policy=NORMAL, now=NOW):
    return dict(initial_state(), last_check=now, heating_interlock=copy.deepcopy(policy))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        (self.root / 'services').mkdir()
        (self.root / 'services/shelly_plug_manager.json').write_text(json.dumps(CONFIG))
        self.now = NOW
        self.helper = HeatingRainInterlock(self.root, self.runtime, clock=lambda: self.now)
        self.write_state(policy_state())
        self.w = water()
        self.patcher = patch('utils.heating_rain_interlock.water_readings', side_effect=lambda *a: self.w)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.gpio = 1; self.calls = []

    def write_state(self, value):
        (self.runtime / 'state.json').write_text(json.dumps(value))

    def set_boiler(self, value):
        self.calls.append(('boiler', value)); self.gpio = value; return True

    def set_pump(self, cycle, value):
        self.calls.append(('pump', cycle, value)); return True

    def prepare(self, requests=None, pumps=None):
        self.helper.prepare(pumps or {c: 1 for c in CYCLES})
        return self.helper.decide(requests or {c: 1 for c in CYCLES})


class DecisionTests(unittest.TestCase):
    def decide(self, *, temp=60, demand=1, pump=1, previous=None, now=NOW, policy=RAIN):
        return residual_decisions(previous or {}, {c: demand for c in CYCLES},
                                  {c: pump for c in CYCLES}, water(temp, now), policy, now, OPTIONS)

    def test_temperature_boundary_and_independent_circuits(self):
        readings = water()
        readings['2']['supply_c'] = 40
        readings['3']['supply_c'] = 39.9
        readings['4'] = {'supply_c': None, 'fresh': False, 'observed_at': NOW}
        state = residual_decisions({}, {c: 1 for c in CYCLES}, {c: 1 for c in CYCLES},
                                   readings, RAIN, NOW, OPTIONS)
        self.assertEqual([state['cycles'][c]['pump_command'] for c in CYCLES], [1, 0, 0, 0])
        self.assertTrue(state['boiler_inhibited'])
        self.assertEqual(self.decide(temp=40.001)['cycles']['1']['pump_command'], 1)

    def test_no_demand_and_master_off_override_hot_water(self):
        self.assertEqual(self.decide(demand=0)['cycles']['1']['pump_command'], 0)
        state = residual_decisions({}, {c: 1 for c in CYCLES}, {c: 1 for c in CYCLES},
                                   water(), RAIN, NOW, OPTIONS, master_on=False)
        self.assertFalse(any(v['pump_command'] for v in state['cycles'].values()))

    def test_normal_heating_does_not_depend_on_hot_water(self):
        self.assertEqual(self.decide(temp=None, policy=NORMAL)['cycles']['1']['pump_command'], 1)

    def test_two_distinct_fresh_samples_required_to_start(self):
        first = self.decide(pump=0)
        self.assertEqual(first['cycles']['1']['pump_command'], 0)
        repeated = residual_decisions(first, {c: 1 for c in CYCLES}, {c: 0 for c in CYCLES},
                                      water(now=NOW), RAIN, NOW + 60, OPTIONS)
        self.assertEqual(repeated['cycles']['1']['warm_samples'], 1)
        self.assertEqual(repeated['cycles']['1']['pump_command'], 0)
        second = self.decide(pump=0, previous=repeated, now=NOW + 120)
        self.assertEqual(second['cycles']['1']['pump_command'], 1)

    def test_cooling_or_missing_data_stops_immediately(self):
        for temp in (40, 39.9, None):
            state = self.decide(temp=temp, previous=self.decide())
            self.assertEqual(state['cycles']['1']['pump_command'], 0)
            self.assertEqual(state['cycles']['1']['warm_samples'], 0)

    def test_restart_waits_five_minutes_and_sustained_warmth(self):
        old = self.decide()
        old['cycles']['1'].update(pump_actual=0, last_stop_at=NOW)
        early = self.decide(previous=old, pump=0, now=NOW + 60)
        self.assertEqual(early['cycles']['1']['reason'], 'minimum_off_time')
        state = early
        for elapsed in (120, 180, 240, 300):
            state = self.decide(previous=state, pump=0, now=NOW + elapsed)
        self.assertEqual(state['cycles']['1']['pump_command'], 1)

    def test_gap_clock_rollback_and_older_samples_do_not_credit_warmth(self):
        old = self.decide(pump=0)
        for now in (NOW - 1, NOW + 181):
            new = self.decide(previous=old, pump=0, now=now)
            self.assertEqual(new['cycles']['1']['warm_samples'], 1)
        old['cycles']['1']['warm_samples'] = 2
        new = residual_decisions(old, {c: 1 for c in CYCLES}, {c: 0 for c in CYCLES},
                                 water(now=NOW - 30), RAIN, NOW + 60, OPTIONS)
        self.assertEqual(new['cycles']['1']['warm_samples'], 1)


class CoordinationTests(unittest.TestCase):
    def state(self, desired=True, latched=False, old=None):
        return dict(policy_state(old or NORMAL), desired_on=desired, rain_latched=latched)

    def test_fresh_matching_off_ack_required_before_any_power_restore(self):
        old = self.state(False, True, RAIN)
        state = self.state(True, old=RAIN)
        p = coordinate(state, old, {}, NOW, lambda: 'attempt-one')
        self.assertTrue(p['inhibit']); self.assertFalse(state['desired_on'])
        self.assertEqual(p['phase'], 'restore_pending')
        valid = {'version': 1, 'restore_token': p['restore_token'], 'checked_at': NOW,
                 'boiler_off_confirmed': True, 'boiler_state': 0}
        for changed in ({'restore_token': 'old'}, {'checked_at': NOW - 181},
                        {'boiler_off_confirmed': False}, {'boiler_state': 1}):
            self.assertFalse(acknowledgement_valid(p, dict(valid, **changed), NOW))
        next_state = dict(copy.deepcopy(state), desired_on=True)
        coordinate(next_state, state, valid, NOW + 60)
        self.assertTrue(next_state['desired_on'])
        self.assertTrue(next_state['heating_interlock']['inhibit'])
        next_state['plugs']['one'] = {'reachable': True, 'output_on': True, 'seen': True,
                                      'protection_latched': False, 'checked_at': NOW + 60}
        self.assertTrue(finish_restoration(next_state, CONFIG, valid, NOW + 60))
        self.assertFalse(next_state['heating_interlock']['inhibit'])

    def test_new_rain_or_weather_failure_cancels_old_restoration_token(self):
        pending = dict(RAIN, phase='restore_pending', restore_token='old', requested_at=NOW)
        for desired, latched in ((False, True), (None, False)):
            state = self.state(desired, latched, pending)
            coordinate(state, self.state(old=pending), {}, NOW + 60)
            self.assertIsNone(state['heating_interlock']['restore_token'])
            self.assertTrue(state['heating_interlock']['inhibit'])

    def test_weather_failure_in_normal_mode_does_not_invent_rain(self):
        state = self.state(None)
        coordinate(state, self.state(), {}, NOW)
        self.assertFalse(state['heating_interlock']['inhibit'])
        self.assertIsNone(state['desired_on'])

    def test_partial_restoration_holds_existing_on_plugs_without_cycling(self):
        restoring = dict(RAIN, phase='restoring_power', restore_token='attempt', requested_at=NOW)
        old = self.state(True, old=restoring); state = copy.deepcopy(old)
        coordinate(state, old, {}, NOW + 300)
        self.assertIsNone(state['desired_on'])
        self.assertTrue(state['heating_interlock']['inhibit'])

    def test_missing_stale_or_malformed_policy_cannot_allow_boiler(self):
        for value in (None, {}, policy_state(now=NOW - 181),
                      policy_state(dict(NORMAL, phase='restore_pending'))):
            self.assertTrue(policy_from_state(value, NOW)['inhibit'])


class ActuationTests(Fixture):
    def test_rain_appearing_after_voting_blocks_boiler_on(self):
        self.prepare()
        self.write_state(policy_state(RAIN))
        result = self.helper.actuate('boiler', 1, self.set_boiler, lambda: self.gpio, self.set_pump)
        self.assertEqual(result, (0, True))
        self.assertNotIn(('boiler', 1), self.calls)

    def test_old_command_generation_is_blocked_after_restoration(self):
        self.write_state(policy_state(dict(NORMAL, generation='new-episode')))
        self.prepare()
        self.assertEqual(self.helper.actuate('boiler', 1, self.set_boiler, lambda: self.gpio,
                                            self.set_pump, generation='old-episode'), (0, True))
        self.assertEqual(self.helper.actuate('boiler', 1, self.set_boiler, lambda: self.gpio,
                                            self.set_pump, generation='new-episode'), (1, True))

    def test_queued_pump_on_is_rechecked_against_new_cold_water(self):
        self.prepare()
        self.write_state(policy_state(RAIN)); self.w = water(40)
        self.helper.actuate('pump_1', 1, self.set_boiler, lambda: self.gpio, self.set_pump)
        self.assertEqual(self.calls, [('pump', '1', 0)])

    def test_cold_stop_timer_and_ack_survive_reload(self):
        pending = dict(RAIN, phase='restore_pending', restore_token='token', requested_at=NOW)
        self.write_state(policy_state(pending)); self.w = water(39)
        self.prepare()
        self.helper.actuate('pump_1', 0, self.set_boiler, lambda: self.gpio, self.set_pump)
        self.helper.ensure_boiler_off(self.set_boiler, lambda: self.gpio)
        self.helper.publish_ack({'boiler_state': self.gpio})
        ack = json.loads((self.runtime / 'heating_status.json').read_text())
        self.assertTrue(ack['boiler_off_confirmed'])
        self.assertEqual(ack['restore_token'], 'token')
        self.assertEqual(ack['cycles']['1']['last_stop_at'], NOW)

    def test_failed_gpio_readback_never_acknowledges_boiler_off(self):
        self.write_state(policy_state(RAIN)); self.prepare()
        self.helper.ensure_boiler_off(Mock(return_value=True), lambda: 1)
        self.helper.publish_ack({'boiler_state': 1})
        ack = json.loads((self.runtime / 'heating_status.json').read_text())
        self.assertFalse(ack['boiler_off_confirmed'])

    def test_preview_cannot_write_or_actuate(self):
        helper = HeatingRainInterlock(self.root, self.runtime, readonly=True, clock=lambda: NOW)
        helper.prepare({c: 1 for c in CYCLES}); helper.decide({c: 1 for c in CYCLES})
        with self.assertRaises(RuntimeError):
            helper.actuate('boiler', 1, self.set_boiler, lambda: self.gpio, self.set_pump)
        helper.publish_ack({'boiler_state': 1})
        self.assertFalse((self.runtime / 'heating_status.json').exists())
        self.assertEqual(self.calls, [])

    def test_intentional_pending_restore_remains_suppressed_in_watchdog(self):
        state = policy_state(dict(RAIN, phase='restore_pending', restore_token='t', requested_at=NOW))
        state['plugs']['one'] = {'mac': SHELLY['devices']['one']['mac']}
        self.write_state(state)
        self.assertTrue(off_expected('one', SHELLY['devices']['one']['mac'], NOW, self.runtime / 'state.json'))


class ManagerPipelineTests(Fixture):
    def test_complete_shutdown_dry_hour_ack_power_restore_and_boiler_resume(self):
        state = initial_state(); relay = {'on': True}; events = []
        client = Mock()
        client.resolve.return_value = 'test'
        client.status.side_effect = lambda ip: {'output': relay['on'], 'errors': []}
        def set_output(ip, on):
            events.append(('relay', on)); relay['on'] = on
            return {'output': on, 'errors': []}
        client.set_output.side_effect = set_output
        reader = Mock()
        def cycle(now, amount):
            reader.read.return_value = {'source': 'WS90', 'amount_mm': amount, 'source_errors': {}}
            return manager.run_once(state, reader, CONFIG, SHELLY, client, now,
                                     save=self.write_state)
        with patch.object(manager, 'RUNTIME_DIR', self.runtime):
            state = cycle(NOW, 11)
            self.assertEqual(events, [('relay', False)])
            for minute in range(1, 62):
                state = cycle(NOW + minute * 60, 0)
            self.assertEqual(state['heating_interlock']['phase'], 'restore_pending')
            self.assertFalse(relay['on'])
            self.now = NOW + 61 * 60
            self.w = water(now=self.now)
            self.prepare()
            def gpio(value):
                events.append(('gpio', value)); return self.set_boiler(value)
            self.helper.ensure_boiler_off(gpio, lambda: self.gpio)
            self.helper.publish_ack({'boiler_state': self.gpio})
            state = cycle(NOW + 62 * 60, 0)
            self.assertTrue(relay['on'])
            self.assertFalse(state['heating_interlock']['inhibit'])
            self.assertLess(events.index(('gpio', 0)), events.index(('relay', True)))
            self.now = NOW + 63 * 60; state['last_check'] = self.now; self.write_state(state)
            self.prepare()
            self.assertEqual(self.helper.actuate('boiler', 1, gpio, lambda: self.gpio,
                                                self.set_pump, generation=state['heating_interlock']['generation']), (1, True))

    def test_rain_mains_cut_does_not_wait_for_gpio_permission_lock(self):
        reader = Mock(); reader.read.return_value = {'source': 'WS90', 'amount_mm': 11, 'source_errors': {}}
        client = Mock(); client.status.return_value = {'output': True, 'errors': []}
        client.resolve.return_value = 'test'
        client.set_output.return_value = {'output': False}
        with patch.object(manager, 'RUNTIME_DIR', self.runtime), patch.object(
                manager, 'permission_lock', side_effect=RuntimeError('lock busy')):
            state = manager.run_once(initial_state(), reader, CONFIG, SHELLY, client, NOW,
                                     save=self.write_state)
        client.set_output.assert_called_once()
        self.assertTrue(state['heating_interlock']['inhibit'])


class WaterInputTests(unittest.TestCase):
    def test_latest_complete_snapshot_validates_each_circuit_and_age(self):
        import io
        from zoneinfo import ZoneInfo
        stamp = datetime.fromtimestamp(NOW, ZoneInfo('Europe/Budapest')).strftime('%Y-%m-%d-%H-%M-%S')
        payload = {'timestamp': stamp, 'states': {str(i): {'flow_temperature_c': t}
                   for i, t in enumerate((60, 40, None, 60), 1)}}
        payload['states']['3'] = None  # One broken record cannot hide the next meter.
        config = {'cycles': {str(i): {'meter': i} for i in range(1, 5)}}
        with patch('utils.heating_rain_interlock.read_json', return_value=config), patch.object(
                Path, 'open', side_effect=lambda *a, **k: io.BytesIO((json.dumps(payload)+'\n{partial').encode())):
            values = water_readings('/unused', NOW, OPTIONS)
            self.assertEqual([values[c]['fresh'] for c in CYCLES], [True, True, False, True])
            self.assertFalse(any(x['fresh'] for x in water_readings('/unused', NOW + 181, OPTIONS).values()))


class ControllerIntegrationTests(Fixture):
    def test_heat_requests_survive_while_cold_pump_and_boiler_are_blocked(self):
        from services import test_heating_control_pid_candidate as tests
        self.write_state(policy_state(RAIN)); self.w['1']['supply_c'] = 39
        logs, errors, writes, saved = tests.ControlIntegrationTests().run_control(
            room_updates={'2': {'cycle': '2'}}, state_updates={'pump_states': {'1': 1, '2': 1}},
            env_updates={'rain_interlock': self.helper})
        control = saved['system/control.json']
        self.assertEqual(control['heat_requests'], {'1': 1, '2': 1, '3': 0, '4': 0})
        self.assertEqual(control['cycles'], {'1': 0, '2': 1, '3': 0, '4': 0})
        self.assertEqual(control['boiler'], 0)
        self.assertEqual(control['rooms']['1']['vote'], 1)
        self.assertFalse(errors)

    def execution_env(self, commands, boiler_set=None):
        from services import test_heating_control_pid_candidate as tests
        env = tests.load_calculations()
        class Clock(datetime):
            @classmethod
            def now(cls): return tests.NOW
        env.update(datetime=Clock, rain_interlock=self.helper,
                   system_state={'pump_states': {c: 1 for c in CYCLES}, 'boiler_state': self.gpio},
                   load_commands=Mock(return_value=commands), refresh_commands=Mock(), archive_commands=Mock(),
                   COMMANDS_PATH='unused', report=Mock(), log=Mock(),
                   set_boiler_state=boiler_set or self.set_boiler, get_boiler_state=lambda: self.gpio,
                   set_pump_state=self.set_pump, ServiceException=Mock(), ModuleException=RuntimeError,
                   system_node=Mock(), timestamp=lambda: tests.NOW.strftime(tests.FMT),
                   timestamp_to_datetime=lambda t: datetime.strptime(t, tests.FMT))
        return env

    def command(self, device='boiler', future=False):
        from services import test_heating_control_pid_candidate as tests
        return {'device': device, 'setting': 1, 'executed': False,
                'issuance_timestamp': (tests.NOW - timedelta(minutes=2)).strftime(tests.FMT),
                'due_timestamp': (tests.NOW + timedelta(minutes=1 if future else -1)).strftime(tests.FMT)}

    def test_executor_discards_due_and_future_boiler_on_commands_in_rain(self):
        self.write_state(policy_state(RAIN)); self.prepare()
        env = self.execution_env([self.command(), self.command(future=True), self.command('pump_1')])
        env['execute_commands']()
        self.assertNotIn(('boiler', 1), self.calls)
        self.assertIn(('pump', '1', 1), self.calls)
        self.assertFalse(any(c['device'] == 'boiler' and c['setting'] == 1
                             for c in env['refresh_commands'].call_args.args[0]))
        self.assertTrue(json.loads((self.runtime / 'heating_status.json').read_text())['boiler_off_confirmed'])

    def test_gpio_failure_does_not_prevent_eligible_pump_control(self):
        self.write_state(policy_state(RAIN)); self.prepare()
        env = self.execution_env([self.command('pump_1')], Mock(side_effect=OSError('GPIO failed')))
        env['execute_commands']()
        self.assertIn(('pump', '1', 1), self.calls)
        self.assertFalse(json.loads((self.runtime / 'heating_status.json').read_text())['boiler_off_confirmed'])

    def test_guarded_effective_commands_are_republished_after_actuation(self):
        self.prepare(); self.helper.control = {'cycles': {c: 1 for c in CYCLES}, 'boiler': 1}
        self.helper.control['rain_protection'] = self.helper.status
        self.write_state(policy_state(RAIN)); self.w = water(40)
        env = self.execution_env([self.command('pump_1'), self.command()])
        env['export_dict_as_json'] = Mock()
        env['execute_commands']()
        published = env['export_dict_as_json'].call_args.args[0]
        self.assertEqual(published['boiler'], 0)
        self.assertEqual(published['cycles']['1'], 0)
        self.assertTrue(published['rain_protection']['boiler_inhibited'])

    def test_boiler_is_disabled_even_if_command_file_cannot_be_read(self):
        self.write_state(policy_state(RAIN)); self.prepare()
        env = self.execution_env([]); env['load_commands'].side_effect = RuntimeError('invalid queue')
        env['execute_commands']()
        self.assertEqual(self.gpio, 0)
        self.assertTrue(json.loads((self.runtime / 'heating_status.json').read_text())['boiler_off_confirmed'])

    def test_old_generation_queue_cannot_reactivate_boiler_after_dry_recovery(self):
        self.write_state(policy_state(dict(NORMAL, generation='new'))); self.prepare()
        env = self.execution_env([self.command()]); env['execute_commands']()
        self.assertNotIn(('boiler', 1), self.calls)
        self.assertEqual(env['system_state']['boiler_state'], 0)

    def test_pid_integral_freezes_during_unavailable_heat_without_resume_kick(self):
        from services import test_heating_control_pid_candidate as tests
        env = tests.load_calculations(); gains = env['read_pid_gains'](tests.GAINS)
        prev = tests.PIDTests(); prev.setUp()
        previous = prev.state(integral=1)
        args = (21, 20, tests.NOW.strftime(tests.FMT), 10, 2, previous, gains, tests.NOW)
        held = env['calculate_pid_overlay'](*args, heating_available=False)
        self.assertEqual(held['next_state']['bias_I'], 1)
        now = tests.NOW + timedelta(seconds=60)
        resumed = env['calculate_pid_overlay'](21, 20, now.strftime(tests.FMT), 10, 2,
                                               held['next_state'], gains, now)
        self.assertEqual(resumed['next_state']['bias_I'], 1)
        self.assertEqual(resumed['log']['state']['dt_PID'], 0)

    def test_intentional_shutdown_clears_cold_boiler_diagnostic(self):
        from services.test_heating_control_reporting import load_reporting
        env = load_reporting(); env['rain_interlock'] = Mock()
        env['rain_interlock'].generation_expected.return_value = False
        env['system_state']['boiler_error'] = 'old fault'
        env['export_system_state']()
        env['read_boiler_error'].assert_not_called()
        self.assertEqual(env['system_state']['boiler_error'], '')


class MonitorContextTests(unittest.TestCase):
    def test_missing_water_is_monitored_even_when_it_blocks_residual_pump(self):
        from services.test_heating_monitor import configuration, sample
        from utils.heating_monitor import evaluate, new_state
        config = configuration(); state = new_state()
        for offset in range(0, 420, 60):
            snapshot = sample(NOW + offset, on=False, supply=20, heat=0, pump=0)
            snapshot['commands'].update(boiler_inhibited=True, heat_requests={c: True for c in CYCLES})
            snapshot['heatmeters']['1']['error'] = 'unavailable'
            state, _ = evaluate(state, snapshot, config)
        self.assertIn('1:meter_data', state['incidents'])
        self.assertFalse(any(key.endswith(':pump') or key.endswith(':flow') for key in state['incidents']))

    def test_residual_heat_suppresses_only_heat_generation_faults(self):
        from services.test_heating_monitor import configuration, sample
        from utils.heating_monitor import evaluate, new_state
        config = configuration(); state = new_state()
        for offset in range(0, 1260, 60):
            snapshot = sample(NOW + offset, supply=20, heat=0, pump=0)
            snapshot['commands'].update(boiler=False, boiler_inhibited=True)
            state, _ = evaluate(state, snapshot, config)
        self.assertIn('1:pump', state['incidents'])
        self.assertFalse(any(key.endswith(':heat') for key in state['incidents']))

    def test_generation_warmup_restarts_after_restoration(self):
        from services.test_heating_monitor import configuration, sample
        from utils.heating_monitor import evaluate, new_state
        config = configuration(); state = new_state()
        for offset in range(0, 1260, 60):
            snapshot = sample(NOW + offset, supply=50, heat=0)
            snapshot['commands'].update(boiler=False, boiler_inhibited=True)
            state, _ = evaluate(state, snapshot, config)
        restored = NOW + 1260
        for offset in range(0, 600, 60):
            snapshot = sample(restored + offset, supply=20, heat=0)
            snapshot['commands'].update(boiler=True, boiler_inhibited=False, heat_restored_at=restored)
            state, _ = evaluate(state, snapshot, config)
        self.assertFalse(any(key.endswith(':heat') for key in state['incidents']))


if __name__ == '__main__':
    unittest.main()
