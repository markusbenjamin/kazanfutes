"""Rain policy, causal source validation, relay safety and watchdog integration."""

import copy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.shelly_plug_manager import (
    PlugClient, control_plugs, deliver_alerts, load_state, publish_status, run_once,
)
from utils.device_watchdog import candidates_for
from utils.rain_plug_control import (
    LOCAL_ZONE, WeatherReader, advance, initial_state, off_expected,
    parse_open_meteo, update_issue, ws90_rainfall,
)


NOW = datetime(2026, 11, 13, 0, 15, tzinfo=LOCAL_ZONE).timestamp()
MAC = '00:11:22:33:44:55'
CONFIG = {'plugs': {'one': {}, 'two': {'optional_until_seen': True}}}
SHELLY = {'devices': {'one': {'mac': MAC}, 'two': {'mac': '00:11:22:33:44:66'}}}


def weather(amount=0, source='WS90'):
    return {'source': source, 'amount_mm': amount, 'source_errors': {}}


def wet_state():
    return advance(initial_state(), weather(11), NOW)


def pass_minutes(state, minutes, amount=0, source='WS90'):
    for _ in range(minutes):
        state = advance(state, weather(amount, source), state['last_check'] + 60)
    return state


class PolicyTests(unittest.TestCase):
    def test_off_is_strictly_above_ten(self):
        self.assertTrue(advance(initial_state(), weather(10), NOW)['desired_on'])
        self.assertFalse(advance(initial_state(), weather(10.01), NOW)['desired_on'])

    def test_latched_between_thresholds(self):
        state = pass_minutes(wet_state(), 120, 7)
        self.assertFalse(state['desired_on'])
        self.assertIsNone(state['dry_since'])

    def test_recovery_needs_full_hour_after_first_low_reading(self):
        state = pass_minutes(wet_state(), 60)
        self.assertFalse(state['desired_on'])  # Only 59 minutes since first low.
        self.assertTrue(pass_minutes(state, 1)['desired_on'])

    def test_exactly_five_resets_recovery(self):
        state = pass_minutes(wet_state(), 40)
        state = pass_minutes(state, 1, 5)
        self.assertIsNone(state['dry_since'])
        self.assertFalse(pass_minutes(state, 60)['desired_on'])

    def test_missing_sources_holds_even_rain_latched(self):
        state = advance(wet_state(), weather(None, None), NOW + 60)
        self.assertIsNone(state['desired_on'])
        self.assertTrue(state['rain_latched'])
        self.assertIsNone(state['dry_since'])
        self.assertFalse(pass_minutes(state, 1)['desired_on'])

    def test_outage_without_prior_rain_requires_recovery_before_on(self):
        state = advance(initial_state(), weather(None, None), NOW)
        self.assertIsNone(pass_minutes(state, 60)['desired_on'])
        self.assertTrue(pass_minutes(state, 61)['desired_on'])

    def test_restart_and_source_change_do_not_credit_old_dry_time(self):
        for kwargs, source in [({'restarted': True}, 'WS90'), ({}, 'Open-Meteo')]:
            state = pass_minutes(wet_state(), 50)
            now = state['last_check'] + 60
            state = advance(state, weather(0, source), now, **kwargs)
            self.assertEqual(state['dry_since'], now)
            self.assertFalse(pass_minutes(state, 59, source=source)['desired_on'])
            self.assertTrue(pass_minutes(state, 60, source=source)['desired_on'])

    def test_gap_and_clock_rollback_reset_timer(self):
        for jump in (600, -600):
            state = pass_minutes(wet_state(), 50)
            now = state['last_check'] + jump
            state = advance(state, weather(), now)
            self.assertEqual(state['dry_since'], now)
            self.assertFalse(state['desired_on'])

    def test_new_rain_resets_recovery_and_immediately_shuts_down(self):
        state = pass_minutes(wet_state(), 50)
        state = pass_minutes(state, 1, 11)
        self.assertIsNone(state['dry_since'])
        state = pass_minutes(state, 61)
        self.assertTrue(state['desired_on'])
        self.assertFalse(pass_minutes(state, 1, 11)['desired_on'])

    def test_input_state_is_not_mutated(self):
        old = wet_state(); original = copy.deepcopy(old)
        advance(old, weather(), NOW + 60)
        self.assertEqual(old, original)


def log_rows(*, gap=False, reset=False, stale=False):
    rows = []
    for minute in range(-35, 1):
        if gap and -18 <= minute <= -13:
            continue
        t = datetime.fromtimestamp(NOW + minute * 60 - (600 if stale else 0), LOCAL_ZONE)
        stamp = t.strftime('%Y-%m-%d-%H-%M-%S')
        value = (100 + minute + 35) if not (reset and minute >= -10) else 0
        rows.append(json.dumps({'timestamp': stamp, 'last_updated': stamp,
                                'state': {'precipitation_mm': value}}))
    return '\n'.join(rows) + '\n{partial'


class SourceTests(unittest.TestCase):
    def test_ws90_crosses_midnight_and_uses_past_half_hour(self):
        paths = []
        def open_log(path, *args, **kwargs):
            paths.append(str(path))
            return io.StringIO(log_rows())
        with patch.object(Path, 'open', open_log):
            result = ws90_rainfall('/unused', NOW)
        self.assertEqual(result['amount_mm'], 30)
        self.assertEqual(result['window_end'], NOW)
        self.assertTrue(any('2026-11-12' in p for p in paths))

    def test_ws90_gaps_resets_and_staleness_are_unavailable(self):
        for options in ({'gap': True}, {'reset': True}, {'stale': True}):
            with self.subTest(options=options), patch.object(Path, 'open',
                    lambda *a, **k: io.StringIO(log_rows(**options))):
                with self.assertRaises(ValueError):
                    ws90_rainfall('/unused', NOW)

    def payload(self):
        end = NOW // 900 * 900
        return {'minutely_15_units': {'precipitation': 'mm'}, 'minutely_15': {
            'time': [end - 1800, end - 900, end, end + 900],
            'precipitation': [99, 3, 4, 1000]}}

    def test_web_uses_two_completed_intervals_and_excludes_future(self):
        result = parse_open_meteo(self.payload(), NOW + 420)
        self.assertEqual(result['amount_mm'], 7)
        self.assertLessEqual(result['window_end'], NOW + 420)
        self.assertEqual(result['window_start'], NOW - 1800)

    def test_web_rejects_bad_units_null_negative_stale_and_missing_interval(self):
        payloads = []
        p = self.payload(); p['minutely_15_units']['precipitation'] = 'inch'; payloads.append(p)
        for value in (None, -1, True, float('nan')):
            p = self.payload(); p['minutely_15']['precipitation'][2] = value; payloads.append(p)
        p = self.payload(); p['minutely_15']['time'][1] -= 1; payloads.append(p)
        for payload in payloads:
            with self.assertRaises((ValueError, TypeError)):
                parse_open_meteo(payload, NOW)
        with self.assertRaises(ValueError):
            parse_open_meteo(self.payload(), NOW + 5000)

    def test_source_fallback_and_double_failure(self):
        reader = WeatherReader('/unused', 47, 19)
        with patch('utils.rain_plug_control.ws90_rainfall', side_effect=ValueError('stale')):
            reader.fallback = Mock(return_value={'source': 'Open-Meteo', 'amount_mm': 7})
            self.assertEqual(reader.read(NOW)['source'], 'Open-Meteo')
            reader.fallback.side_effect = ValueError('web failure')
            self.assertIsNone(reader.read(NOW)['amount_mm'])

    def test_expired_cached_intervals_trigger_immediate_refresh(self):
        session = Mock()
        reader = WeatherReader('/unused', 47, 19, session=session)
        reader.cached, reader.fetched_at = self.payload(), NOW + 800
        reader.cached['minutely_15'] = {
            key: values[:-1] for key, values in reader.cached['minutely_15'].items()}
        fresh = self.payload()
        fresh['minutely_15']['time'] = [t + 900 for t in fresh['minutely_15']['time']]
        session.get.return_value.json.return_value = fresh
        reader.fallback(NOW + 1000)
        session.get.assert_called_once()


class RelayTests(unittest.TestCase):
    def test_relay_readback_failure_is_not_reported_as_success(self):
        client = PlugClient.__new__(PlugClient)
        client.rpc = Mock(return_value={})
        client.status = Mock(return_value={'output': True})
        with self.assertRaises(RuntimeError):
            client.set_output('test', False)

    def test_corrupt_state_does_not_discard_persistent_latch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text('{partial')
            with self.assertRaises(ValueError):
                load_state(path)
            state = initial_state(); state['rain_latched'] = 'false'
            path.write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                load_state(path)

    def client(self, output=False, errors=None):
        client = Mock()
        client.resolve.side_effect = lambda name: name
        client.status.return_value = {'output': output, 'errors': errors or []}
        client.set_output.side_effect = lambda ip, on: {'output': on, 'errors': []}
        return client

    def test_unexpected_off_is_restored_only_in_normal_mode(self):
        for state, count in [(advance(initial_state(), weather(), NOW), 2),
                             (advance(initial_state(), weather(None, None), NOW), 0),
                             (wet_state(), 0)]:
            client = self.client()
            control_plugs(state, CONFIG, SHELLY, client, NOW)
            self.assertEqual(client.set_output.call_count, count)

    def test_rain_shuts_down_and_saves_before_switching(self):
        client = self.client(output=True)
        saved = []
        client.set_output.side_effect = lambda ip, on: saved.append(('switch', on)) or {'output': on}
        control_plugs(wet_state(), CONFIG, SHELLY, client, NOW,
                      save=lambda: saved.append(('saved', False)))
        self.assertEqual(saved[0], ('saved', False))
        self.assertEqual(saved[1], ('switch', False))

    def test_dry_run_never_switches_and_marks_proposed_action(self):
        client = self.client(output=True)
        result = control_plugs(wet_state(), CONFIG, SHELLY, client, NOW, dry_run=True)
        client.set_output.assert_not_called()
        self.assertIs(result['one']['would_set_on'], False)

    def test_fault_latch_prevents_later_automatic_rearm(self):
        state = advance(initial_state(), weather(), NOW)
        client = self.client(errors=['overtemp'])
        control_plugs(state, CONFIG, SHELLY, client, NOW)
        client.set_output.assert_not_called()
        client.status.return_value = {'output': False, 'errors': []}
        control_plugs(state, CONFIG, SHELLY, client, NOW + 60)
        client.set_output.assert_not_called()
        self.assertTrue(state['plugs']['one']['protection_latched'])

    def test_plug_two_missing_is_optional_until_seen(self):
        state = advance(initial_state(), weather(), NOW)
        client = self.client()
        client.resolve.side_effect = RuntimeError('missing')
        control_plugs(state, CONFIG, SHELLY, client, NOW)
        self.assertIn('plug:one', state['issues'])
        self.assertNotIn('plug:two', state['issues'])
        state['plugs']['two']['seen'] = True
        control_plugs(state, CONFIG, SHELLY, client, NOW + 60)
        self.assertIn('plug:two', state['issues'])

    def test_pipeline_persists_wet_latch_before_actuation(self):
        reader = Mock(); reader.read.return_value = weather(11)
        client = self.client(output=True); saves = []
        client.set_output.side_effect = lambda ip, on: self.assertTrue(saves[-1]['rain_latched']) or {'output': on}
        run_once(initial_state(), reader, CONFIG, SHELLY, client, NOW,
                 save=lambda s: saves.append(copy.deepcopy(s)))
        self.assertGreaterEqual(len(saves), 3)

    def test_notification_deduplication_and_retry(self):
        state = wet_state(); saved = Mock(); sender = Mock(return_value=False)
        update_issue(state, 'weather', 'failed', NOW)
        deliver_alerts(state, NOW, saved, sender)
        deliver_alerts(state, NOW + 60, saved, sender)
        self.assertEqual(sender.call_count, 1)
        sender.return_value = True
        deliver_alerts(state, NOW + 300, saved, sender)
        deliver_alerts(state, NOW + 600, saved, sender)
        self.assertEqual(sender.call_count, 2)
        update_issue(state, 'weather', None, NOW + 600)
        update_issue(state, 'weather', 'new outage', NOW + 700)
        deliver_alerts(state, NOW + 700, saved, sender)
        self.assertEqual(sender.call_count, 3)


class WatchdogTests(unittest.TestCase):
    def test_suppression_requires_fresh_intent_and_matching_mac(self):
        state = wet_state(); state['plugs']['one'] = {'mac': MAC}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'; path.write_text(json.dumps(state))
            self.assertTrue(off_expected('one', MAC, NOW, path))
            self.assertFalse(off_expected('one', MAC, NOW + 181, path))
            self.assertFalse(off_expected('one', 'different', NOW, path))
            self.assertFalse(off_expected('one', MAC, NOW - 1, path))
            state['rain_latched'] = state['recovery_required'] = False
            path.write_text(json.dumps(state))
            self.assertFalse(off_expected('one', MAC, NOW, path))

    def test_intentional_off_keeps_connectivity_and_fault_checks(self):
        device = {'device_id': 'test', 'name': 'test', 'profile': 'boiler_power_plug',
                  'facts': {'armed': True, 'reachable': True, 'output_on': False,
                            'rain_off_expected': True}}
        now = datetime.fromtimestamp(NOW, LOCAL_ZONE)
        self.assertEqual(candidates_for(device, {}, now), [])
        device['facts']['switch_errors'] = ['overtemp']
        self.assertEqual(candidates_for(device, {}, now)[0]['kind'], 'switch_fault')
        device['facts']['reachable'] = False
        self.assertEqual(candidates_for(device, {}, now)[0]['kind'], 'state_unknown')


class FirebaseTests(unittest.TestCase):
    def test_patch_is_confined_to_rain_protection_child(self):
        session = Mock(); state = pass_minutes(wet_state(), 10)
        state['plugs']['one'] = {'reachable': True, 'output_on': False}
        publish_status(state, NOW + 600, 'https://firebase.test/', session=session)
        args, kwargs = session.patch.call_args
        self.assertEqual(args, ('https://firebase.test/system/state.json',))
        self.assertEqual(set(kwargs['json']), {'rain_protection'})
        status = kwargs['json']['rain_protection']
        self.assertEqual(status['dry_hour_remaining_seconds'], 3060)
        self.assertTrue(status['rain_shutdown'])
        self.assertFalse(status['automatic_turn_on_allowed'])
        self.assertEqual(kwargs['timeout'], 3)

    def test_stopped_status_is_explicit(self):
        session = Mock()
        publish_status(wet_state(), NOW, 'https://firebase.test', running=False, session=session)
        status = session.patch.call_args.kwargs['json']['rain_protection']
        self.assertEqual(status['mode'], 'stopped')
        self.assertFalse(status['running'])

    def test_firebase_failure_does_not_prevent_control_and_retries_next_cycle(self):
        reader = Mock(); reader.read.return_value = weather(11)
        client = RelayTests().client(output=True)
        publisher = Mock(side_effect=RuntimeError('offline'))
        state = run_once(initial_state(), reader, CONFIG, SHELLY, client, NOW,
                         publisher=publisher)
        self.assertEqual(client.set_output.call_count, 2)
        self.assertEqual(state['firebase']['last_error'], 'offline')
        publisher.side_effect = None
        state = run_once(state, reader, CONFIG, SHELLY, client, NOW + 60, publisher=publisher)
        self.assertEqual(publisher.call_count, 2)
        self.assertIsNone(state['firebase']['last_error'])


if __name__ == '__main__':
    unittest.main()
