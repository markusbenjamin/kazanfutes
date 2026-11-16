"""Local rain/heating permissions and per-circuit residual-heat decisions.

The rain manager alone writes state.json; the heating controller alone writes
heating_status.json. Only permission transitions and boiler GPIO actuation share
a lock. Weather, pump network calls and Firebase never run under that lock.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo
from datetime import datetime

from filelock import FileLock
from utils.device_watchdog import atomic_write_json

RUNTIME = Path('/var/lib/kazanfutes-rain-plugs')
CYCLES = ('1', '2', '3', '4')
MAX_AGE = 180
DEFAULTS = {'enabled': False, 'minimum_supply_c': 40.0,
            'water_max_age_seconds': 180, 'restart_off_seconds': 300,
            'warm_samples_required': 2, 'warmup_seconds': 600}


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else copy.deepcopy(default)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def fresh(stamp, now, max_age=MAX_AGE):
    return (type(stamp) in (int, float) and math.isfinite(stamp)
            and 0 <= now - stamp <= max_age)


def permission_lock(runtime=RUNTIME):
    return FileLock(str(Path(runtime) / 'heat_permission.lock'), timeout=5)


def settings(root):
    config = read_json(Path(root) / 'services/shelly_plug_manager.json')
    if not isinstance(config, dict):
        raise ValueError('Rain configuration unavailable')
    result = dict(DEFAULTS, **config.get('heating_interlock', {}))
    if type(result['enabled']) is not bool:
        raise ValueError('Invalid interlock enabled flag')
    for key in ('minimum_supply_c', 'water_max_age_seconds', 'restart_off_seconds',
                'warm_samples_required', 'warmup_seconds'):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid residual-heat setting: ' + key)
    if type(result['warm_samples_required']) is not int:
        raise ValueError('Warm sample count must be an integer')
    return result


def policy_from_state(state, now):
    bad = {'inhibit': True, 'phase': 'unavailable', 'restore_token': None,
           'generation': None, 'restored_at': None, 'error': 'Rain policy unavailable or stale'}
    if not isinstance(state, dict) or state.get('version') != 1 or not fresh(state.get('last_check'), now):
        return bad
    if type(state.get('rain_latched')) is not bool:
        return bad
    policy = state.get('heating_interlock')
    if policy is None:
        # Controller-first deployment remains compatible with the old manager.
        return dict(bad, inhibit=state['rain_latched'], phase='legacy', error=None)
    if (not isinstance(policy, dict) or policy.get('version') != 1
            or type(policy.get('inhibit')) is not bool
            or policy.get('phase') not in ('normal', 'rain_shutdown', 'restore_pending', 'restoring_power')
            or (not policy['inhibit'] and policy['phase'] != 'normal')
            or (policy.get('generation') is not None and not isinstance(policy['generation'], str))
            or (policy.get('restored_at') is not None and type(policy['restored_at']) not in (float, int))):
        return bad
    if policy['phase'] in ('restore_pending', 'restoring_power') and (
            not isinstance(policy.get('restore_token'), str) or not policy['restore_token']
            or type(policy.get('requested_at')) not in (float, int)):
        return bad
    result = dict(policy, error=None)
    result['inhibit'] = policy['inhibit'] or state['rain_latched']
    return result


def acknowledgement_valid(policy, ack, now):
    return (isinstance(ack, dict) and ack.get('version') == 1
            and bool(policy.get('restore_token'))
            and ack.get('restore_token') == policy['restore_token']
            and fresh(ack.get('checked_at'), now)
            and ack['checked_at'] >= policy['requested_at']
            and ack.get('boiler_off_confirmed') is True
            and ack.get('boiler_state') == 0)


def coordinate(state, previous, ack, now, token_factory=lambda: uuid.uuid4().hex):
    """Prepare permission before relay IO. Called while holding permission lock."""
    old = previous.get('heating_interlock') or {
        'version': 1, 'inhibit': previous.get('rain_latched', False),
        'phase': 'normal', 'generation': None, 'restored_at': None}
    policy = copy.deepcopy(old)
    state['heating_interlock'] = policy
    if state['rain_latched']:
        if not old['inhibit'] or not policy.get('generation'):
            policy['generation'] = token_factory()
        policy.update(inhibit=True, phase='rain_shutdown', restore_token=None)
        policy.setdefault('inhibit_since', now)
        policy.pop('requested_at', None)
    elif old['inhibit']:
        if state['desired_on'] is not True:
            # Weather failure holds physical states and cancels any old unlock.
            policy.update(inhibit=True, phase='rain_shutdown', restore_token=None)
            policy.pop('requested_at', None)
        else:
            if old['phase'] not in ('restore_pending', 'restoring_power'):
                policy.update(inhibit=True, phase='restore_pending',
                              restore_token=token_factory(), requested_at=now)
            permitted = acknowledgement_valid(policy, ack, now)
            if permitted:
                policy['phase'] = 'restoring_power'
                state['desired_on'] = True
            else:
                # Some plugs may already be ON after a partial restoration.
                # Hold them instead of cycling them while awaiting a fresh ack.
                state['desired_on'] = None if old['phase'] == 'restoring_power' else False
            state['mode'] = 'restore_pending'
    else:
        policy.update(inhibit=False, phase='normal', restore_token=None)
    return policy


def finish_restoration(state, config, ack, now):
    """Release generation only after fresh OFF acknowledgement and relay readbacks."""
    policy = state['heating_interlock']
    if policy['phase'] != 'restoring_power' or not acknowledgement_valid(policy, ack, now):
        return False
    required = [state['plugs'].get(name, {}) for name, options in config['plugs'].items()
                if not options.get('optional_until_seen') or state['plugs'].get(name, {}).get('seen')]
    if not required or not all(p.get('reachable') is True and p.get('output_on') is True
                               and not p.get('protection_latched') and not p.get('error')
                               and p.get('checked_at') == now for p in required):
        return False
    policy.update(inhibit=False, phase='normal', restore_token=None, restored_at=now)
    policy.pop('inhibit_since', None)
    state['mode'] = 'normal'
    return True


def water_readings(root, now, config):
    """Bounded, local-only read of the latest complete heatmeter snapshot."""
    result = {c: {'supply_c': None, 'observed_at': None, 'fresh': False} for c in CYCLES}
    mapping = read_json(Path(root) / 'config/heating_monitor.json', {}).get('cycles', {})
    try:
        path = Path(root) / 'data/logs/heat_delivery/heatmeters_state.json'
        with path.open('rb') as handle:
            handle.seek(0, 2)
            offset = max(0, handle.tell() - 65536)
            handle.seek(offset)
            if offset:
                handle.readline()
            lines = handle.read(65536).splitlines()
        snapshot = next(json.loads(line) for line in reversed(lines)
                        if line.strip().startswith(b'{') and _complete_json(line))
        observed = datetime.strptime(snapshot['timestamp'], '%Y-%m-%d-%H-%M-%S').replace(
            tzinfo=ZoneInfo('Europe/Budapest')).timestamp()
        for cycle in CYCLES:
            try:
                meter = mapping[cycle]['meter']
                value = snapshot['states'].get(str(meter), snapshot['states'].get(meter, {})).get('flow_temperature_c')
                usable = type(value) in (int, float) and math.isfinite(value) and 0 < value < 100
                result[cycle] = {'supply_c': value if usable else None, 'observed_at': observed,
                                 'fresh': usable and fresh(observed, now, config['water_max_age_seconds'])}
            except (KeyError, TypeError, AttributeError):
                continue
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        pass
    return result


def _complete_json(line):
    try:
        return isinstance(json.loads(line), dict)
    except (ValueError, UnicodeError):
        return False


def residual_decisions(previous, requests, pumps, water, policy, now, config, master_on=True):
    """Keep raw demand independent from effective pump commands and restart timers."""
    cycles = {}
    gap = not fresh(previous.get('checked_at'), now)
    for cycle in CYCLES:
        old = previous.get('cycles', {}).get(cycle, {})
        reading = water[cycle]
        warm = reading['fresh'] and reading['supply_c'] > config['minimum_supply_c']
        samples = old.get('warm_samples', 0) if not gap else 0
        last_sample = old.get('last_warm_sample') if not gap else None
        if not warm:
            samples, last_sample = 0, None
        elif reading['observed_at'] != last_sample:
            # A repeated cached observation must not count as a second sample.
            if last_sample is not None and reading['observed_at'] < last_sample:
                samples = 0
            samples, last_sample = min(samples + 1, config['warm_samples_required']), reading['observed_at']
        stopped = old.get('last_stop_at')
        if stopped is not None and stopped > now:
            stopped = now
        actual = pumps.get(cycle)
        if actual == 0 and old.get('pump_actual') == 1:
            stopped = now
        requested = bool(master_on and requests.get(cycle))
        desired, reason = int(requested), 'normal'
        if not requested:
            desired, reason = 0, 'no_heat_request' if master_on else 'master_off'
        elif policy['inhibit']:
            if not reading['fresh']:
                desired, reason = 0, 'water_unavailable'
            elif not warm:
                desired, reason = 0, 'water_not_above_40'
            elif actual == 1:
                desired, reason = 1, 'residual_heat'
            elif stopped is not None and now - stopped < config['restart_off_seconds']:
                desired, reason = 0, 'minimum_off_time'
            elif samples < config['warm_samples_required']:
                desired, reason = 0, 'confirming_warm_water'
            else:
                desired, reason = 1, 'residual_heat'
        cycles[cycle] = dict(reading, heat_requested=requested, pump_command=desired,
                             pump_actual=actual, reason=reason, warm_samples=samples,
                             last_warm_sample=last_sample, last_stop_at=stopped)
    return {'version': 1, 'checked_at': now, 'boiler_inhibited': policy['inhibit'],
            'policy_phase': policy['phase'], 'policy_error': policy.get('error'),
            'heat_restored_at': policy.get('restored_at'), 'cycles': cycles}


class HeatingRainInterlock:
    """Heating controller adapter. Device IO is injected through existing helpers."""
    def __init__(self, root, runtime=RUNTIME, *, readonly=False, clock=time.time):
        self.root, self.runtime = Path(root), Path(runtime)
        self.status_path = self.runtime / 'heating_status.json'
        self.state_path = self.runtime / 'state.json'
        self.clock, self.readonly = clock, readonly
        try:
            self.config = settings(root)
            self.config_error = None
        except (ValueError, TypeError):
            self.config = dict(DEFAULTS, enabled=True)
            self.config_error = 'Rain configuration unavailable or invalid'
        self.status, self.requests = {}, {}
        self.master_on = True
        self.boiler_off_confirmed = False
        self.ack_token = None
        self.effective_boiler_command = None

    @property
    def enabled(self):
        return self.config['enabled']

    def policy(self):
        if not self.enabled:
            return {'inhibit': False, 'phase': 'disabled', 'generation': None, 'restored_at': None}
        policy = policy_from_state(read_json(self.state_path), self.clock())
        if self.config_error:
            policy.update(inhibit=True, phase='unavailable', error=self.config_error)
        return policy

    def acquire_loop(self):
        if self.enabled and not self.readonly:
            self._loop_lock = FileLock(str(self.runtime / 'heating_loop.lock'), timeout=0)
            self._loop_lock.acquire()
            import atexit
            atexit.register(self._loop_lock.release)

    def prepare(self, pumps, master_on=True):
        self.master_on = master_on
        self.prepared_policy = self.policy()
        self.previous = read_json(self.status_path, {})
        self.water = water_readings(self.root, self.clock(), self.config)
        self.pumps = dict(pumps)

    def integration_allowed(self, cycle):
        p = self.prepared_policy
        w = self.water[str(cycle)]
        return not p['inhibit'] or (self.pumps.get(str(cycle)) == 1 and w['fresh']
                                    and w['supply_c'] > self.config['minimum_supply_c'])

    def decide(self, requests):
        self.requests = dict(requests)
        self.status = residual_decisions(self.previous, requests, self.pumps, self.water,
                                         self.prepared_policy, self.clock(), self.config, self.master_on)
        votes = {c: v['pump_command'] for c, v in self.status['cycles'].items()}
        boiler = int(any(votes.values()) and not self.prepared_policy['inhibit'] and self.master_on)
        return votes, boiler

    def actuate(self, device, requested, boiler_set, boiler_read, pump_set, *, generation=None):
        if self.readonly:
            raise RuntimeError('Read-only preview cannot operate devices')
        if device == 'boiler':
            with permission_lock(self.runtime):
                policy = self.policy()
                desired = int(bool(requested) and self.master_on and not policy['inhibit']
                              and generation == policy.get('generation'))
                self.effective_boiler_command = desired
                confirmed = bool(boiler_set(desired)) and boiler_read() == desired
                if desired == 0:
                    self.boiler_off_confirmed = confirmed
                    self.ack_token = policy.get('restore_token')
                else:
                    self.boiler_off_confirmed = False
                return desired, confirmed
        cycle = device.removeprefix('pump_')
        desired = int(bool(requested) and self.master_on)
        if desired and self.policy()['inhibit']:
            w = water_readings(self.root, self.clock(), self.config)[cycle]
            already_on = self.pumps.get(cycle) == 1
            qualified = (self.status.get('boiler_inhibited') is True
                         and self.status.get('cycles', {}).get(cycle, {}).get('pump_command') == 1)
            desired = int(bool(self.requests.get(cycle)) and w['fresh']
                          and w['supply_c'] > self.config['minimum_supply_c']
                          and (already_on or qualified))
        item = self.status.get('cycles', {}).get(cycle)
        if item is not None:
            item['pump_command'] = desired
        confirmed = bool(pump_set(cycle, desired))
        if confirmed:
            if item is not None:
                if desired == 0 and self.pumps.get(cycle) == 1:
                    item['last_stop_at'] = self.clock()
                item.update(pump_command=desired, pump_actual=desired)
            self.pumps[cycle] = desired
        return desired, confirmed

    def ensure_boiler_off(self, boiler_set, boiler_read):
        if self.enabled and self.policy()['inhibit']:
            return self.actuate('boiler', 0, boiler_set, boiler_read, None)
        return None

    def publish_ack(self, system_state):
        if not self.enabled or self.readonly:
            return
        current = self.policy()
        self.status.update(boiler_inhibited=current['inhibit'], policy_phase=current['phase'],
                           policy_error=current.get('error'), heat_restored_at=current.get('restored_at'))
        self.status.update(version=1, checked_at=self.clock(), master_on=self.master_on,
                           restore_token=self.ack_token, boiler_off_confirmed=self.boiler_off_confirmed,
                           boiler_state=system_state.get('boiler_state'))
        atomic_write_json(str(self.status_path), self.status)

    def generation_expected(self):
        policy = self.policy()
        restored = policy.get('restored_at')
        return not policy['inhibit'] and (restored is None or self.clock() - restored >= self.config['warmup_seconds'])
