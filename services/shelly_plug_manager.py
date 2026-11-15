"""Manage boiler Shelly plugs using WS90 trailing rain, with web fallback.

Run with --dry-run for one read-only preview, or --show-state for saved status.
The systemd service runs continuously. No thermostat/protection settings change.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filelock import FileLock
import requests

from utils.device_watchdog import atomic_write_json
from utils.rain_plug_control import (
    RUNTIME_DIR, STATE_PATH, WeatherReader, advance, initial_state, update_issue,
    number, MAX_AGE, OFF_ABOVE_MM, RETURN_BELOW_MM, RECOVERY_SECONDS,
)
from utils.shelly_discovery import build_shelly_resolver, load_shelly_config, normalize_mac


class PlugClient:
    def __init__(self, root, config):
        self.config = config
        self.resolver = build_shelly_resolver(str(root), config)
        self.session = requests.Session()
        self.session.trust_env = False
        self.next_scan = {}

    def resolve(self, name):
        expected = normalize_mac(self.config['devices'][name]['mac'])
        for record in self.resolver.discover():
            if record['mac'] != expected:
                continue
            try:
                response = self.session.get('http://' + record['ip'] + '/shelly', timeout=2)
                response.raise_for_status()
                if normalize_mac(response.json()['mac']) == expected:
                    return record['ip']
            except (requests.RequestException, ValueError, KeyError):
                pass
        now = time.monotonic()
        if now < self.next_scan.get(name, 0):
            raise RuntimeError('Device not reachable; discovery retry is pending')
        self.next_scan[name] = now + 300
        return self.resolver.resolve_one(name, self.config['devices'][name])['ip']

    def rpc(self, ip, method, **params):
        response = self.session.post('http://' + ip + '/rpc',
                                     json={'id': 1, 'method': method, 'params': params}, timeout=3)
        response.raise_for_status()
        payload = response.json()
        if 'error' in payload:
            raise RuntimeError(f'{method}: {payload["error"]}')
        return payload.get('result', payload)

    def status(self, ip):
        result = self.rpc(ip, 'Switch.GetStatus', id=0)
        if not isinstance(result.get('output'), bool):
            raise ValueError('Switch.GetStatus has no boolean output')
        return result

    def set_output(self, ip, on):
        self.rpc(ip, 'Switch.Set', id=0, on=on)
        status = self.status(ip)
        if status['output'] is not on:
            raise RuntimeError('Relay read-back disagrees with requested output')
        return status


def control_plugs(state, config, shelly_config, client, now, *, dry_run=False, save=None):
    """Reconcile reachable devices; persist intent and protection latches before IO."""
    results = {}
    for name, options in config['plugs'].items():
        mac = normalize_mac(shelly_config['devices'][name]['mac'])
        previous = state['plugs'].get(name, {})
        if previous.get('mac') not in (None, mac):
            raise ValueError('Configured plug identity changed; review runtime state first')
        record = dict(previous, mac=mac)
        record.setdefault('seen', False)
        record.setdefault('protection_latched', False)
        record['optional_until_seen'] = bool(options.get('optional_until_seen'))
        state['plugs'][name] = record
        key = 'plug:' + name
        try:
            ip = client.resolve(name)
            status = client.status(ip)
            record.update(seen=True, reachable=True, output_on=status['output'],
                          ip=ip, checked_at=now, errors=status.get('errors') or [])
            if record['errors']:
                record['protection_latched'] = True
                if save and not dry_run:
                    save()
            desired = state['desired_on']
            if desired is True and record.get('protection_latched'):
                raise RuntimeError('Protection fault latched; inspect plug before explicitly clearing it')
            if desired is not None and status['output'] is not desired:
                record['requested_on'] = desired
                if not dry_run:
                    if save:
                        save()
                    status = client.set_output(ip, desired)
                    record['output_on'] = status['output']
                    record['last_change_at'] = now
                else:
                    record['would_set_on'] = desired
            if record.get('protection_latched'):
                raise RuntimeError('Shelly reported an electrical/temperature protection fault')
            update_issue(state, key, None, now)
            record.pop('error', None)
        except Exception as error:
            record['error'] = str(error)
            # A failed command/read must not manufacture a successful output state.
            if 'checked_at' not in record or record['checked_at'] != now:
                record['reachable'] = False
            if record.get('seen') or not options.get('optional_until_seen', False):
                update_issue(state, key, f'{name}: {error}', now)
        results[name] = dict(record)
    return results


def deliver_alerts(state, now, save, sender):
    pending = state.get('pending_notifications', [])
    deliveries = list(state['issues'].items()) + [(issue['key'], issue) for issue in pending]
    for key, issue in deliveries:
        if issue['sent'] or (issue['last_attempt'] is not None and 0 <= now - issue['last_attempt'] < 300):
            continue
        issue['last_attempt'] = now
        save()
        try:
            accepted = sender('[Shelly rain control] ' + key,
                              issue['message'] +
                              ('\n\nThis condition has since cleared; email delivery was delayed.'
                               if issue.get('resolved') else '') +
                              '\n\nController mode: ' + state['mode'])
            if not accepted:
                raise RuntimeError('Notification was not accepted')
            issue['sent'] = True
        except Exception as error:
            print('Email delivery failed; will retry: ' + str(error), flush=True)
        save()
    state['pending_notifications'] = [issue for issue in pending if not issue['sent']]
    save()


def load_state(path):
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return initial_state()
    required = set(initial_state())
    if not isinstance(state, dict) or state.get('version') != 1 or not required <= set(state):
        raise ValueError('Invalid controller state; refusing to discard a possible rain latch')
    if (not all(isinstance(state[key], bool) for key in ('rain_latched', 'recovery_required'))
            or not all(isinstance(state[key], dict) for key in ('plugs', 'issues'))):
        raise ValueError('Invalid controller state types')
    for key in ('dry_since', 'last_check'):
        if state[key] is not None:
            number(state[key])
    return state


def publish_status(state, now, firebase_url, *, running=True, session=requests):
    """PATCH only our child of heating state, after physical control has finished."""
    dry_since = state.get('dry_since')
    payload = {
        'enabled': True, 'running': running,
        'updated_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
        'checked_at_epoch': state['last_check'], 'fresh_for_seconds': MAX_AGE,
        'mode': state['mode'] if running else 'stopped',
        'rain_shutdown': state['rain_latched'],
        'automatic_turn_on_allowed': running and state['desired_on'] is True,
        'rain_30min_mm': state.get('weather', {}).get('amount_mm'),
        'weather_source': state.get('source'),
        'estimated': state.get('weather', {}).get('estimated'),
        'window_start_epoch': state.get('weather', {}).get('window_start'),
        'window_end_epoch': state.get('weather', {}).get('window_end'),
        'dry_hour_remaining_seconds': (max(0, RECOVERY_SECONDS - (now - dry_since))
                                       if dry_since is not None else None),
        'thresholds': {'off_above_mm': OFF_ABOVE_MM, 'return_below_mm': RETURN_BELOW_MM,
                       'window_minutes': 30, 'dry_minutes_required': 60},
        'plugs': {name: {key: plug.get(key) for key in
                        ('reachable', 'output_on', 'seen', 'optional_until_seen',
                         'protection_latched', 'error')}
                  for name, plug in state['plugs'].items()},
        'issues': {key: issue['message'] for key, issue in state['issues'].items()},
    }
    response = session.patch(firebase_url.rstrip('/') + '/system/state.json',
                             json={'rain_protection': payload}, timeout=3)
    response.raise_for_status()
    return True


def run_once(state, reader, config, shelly_config, client, now, *, restarted=False,
             dry_run=False, save=None, sender=None, publisher=None):
    weather = reader.read(now)
    result = advance(state, weather, now, restarted=restarted)
    save_result = (lambda: save(result)) if save else lambda: None
    unavailable = weather['source'] is None
    update_issue(result, 'weather_unavailable',
                 ('WS90 and Open-Meteo are unavailable. Relay states are being held; automatic turn-on is blocked. '
                  'The one-hour recovery timer has been reset.\n' + json.dumps(weather['source_errors']))
                 if unavailable else None, now)
    # Save the rain latch before any relay command, including after a crash.
    if not dry_run:
        save_result()
    control_plugs(result, config, shelly_config, client, now, dry_run=dry_run, save=save_result)
    if not dry_run:
        save_result()
        if publisher:
            publication = result.setdefault('firebase', {})
            try:
                publisher(result, now)
                publication.update(last_success=now, last_error=None)
            except Exception as error:
                publication['last_error'] = str(error)
                print('Firebase rain-protection status failed; local control completed: ' + str(error), flush=True)
            save_result()
        if sender:
            deliver_alerts(result, now, save_result, sender)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='One check; no relay commands, state writes or emails')
    parser.add_argument('--show-state', action='store_true')
    parser.add_argument('--clear-protection', metavar='PLUG', help='After inspection, with the service stopped')
    args = parser.parse_args()
    if args.show_state:
        print(json.dumps(load_state(STATE_PATH), indent=2))
        return
    config = json.loads((ROOT / 'services/shelly_plug_manager.json').read_text())
    shelly_config = load_shelly_config(str(ROOT))
    if not config['plugs'] or not 10 <= config['poll_seconds'] <= 60:
        raise ValueError('Invalid plug list or polling interval')
    for name in config['plugs']:
        normalize_mac(shelly_config['devices'][name]['mac'])
    if args.clear_protection and args.clear_protection not in config['plugs']:
        raise ValueError('Unknown plug')
    if not args.dry_run:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state(STATE_PATH)
    if args.dry_run:
        reader = WeatherReader(ROOT, **config['fallback_location'])
        client = PlugClient(ROOT, shelly_config)
        # Resolver may refresh its shared discovery cache, but cannot switch devices.
        print(json.dumps(run_once(state, reader, config, shelly_config, client,
                                  time.time(), restarted=True, dry_run=True), indent=2))
        return
    with FileLock(str(RUNTIME_DIR / 'controller.lock'), timeout=1):
        save = lambda value: atomic_write_json(str(STATE_PATH), value)
        if args.clear_protection:
            state['plugs'].get(args.clear_protection, {}).pop('protection_latched', None)
            save(state)
            return
        from utils.project import notify_admin, settings
        publisher = lambda value, now: publish_status(value, now, settings['firebase_url'])
        reader = WeatherReader(ROOT, **config['fallback_location'])
        client = PlugClient(ROOT, shelly_config)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        restarted = True
        last_clock, last_monotonic = time.time(), time.monotonic()
        while not stop.is_set():
            now, monotonic = time.time(), time.monotonic()
            clock_changed = abs((now - last_clock) - (monotonic - last_monotonic)) > 5
            state = run_once(state, reader, config, shelly_config, client, now,
                             restarted=restarted or clock_changed, save=save,
                             sender=notify_admin, publisher=publisher)
            print(json.dumps({'checked_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                              'mode': state['mode'], 'rain_30min_mm': state['weather']['amount_mm'],
                              'source': state['source'], 'dry_since': state['dry_since'],
                              'plugs': state['plugs']}), flush=True)
            restarted = False
            last_clock, last_monotonic = now, monotonic
            stop.wait(config['poll_seconds'])
        state['dry_since'] = None
        save(state)
        try:
            publish_status(state, time.time(), settings['firebase_url'], running=False)
        except Exception as error:
            print('Could not publish stopped state to Firebase: ' + str(error), flush=True)


if __name__ == '__main__':
    main()
