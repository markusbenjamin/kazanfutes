"""Causal rainfall selection and persistent Shelly rain-shutdown policy.

Precipitation counters retain the gateway's declared millimetre scale. Open-Meteo
uses the latest two completed 15-minute intervals, never a future/centred bin.
"""

from __future__ import annotations

import bisect
import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


RUNTIME_DIR = Path('/var/lib/kazanfutes-rain-plugs')
STATE_PATH = RUNTIME_DIR / 'state.json'
STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
LOCAL_ZONE = ZoneInfo('Europe/Budapest')
MAX_AGE = 180
WINDOW = 1800
OFF_ABOVE_MM = 10.0
RETURN_BELOW_MM = 5.0
RECOVERY_SECONDS = 3600
MAX_CHECK_GAP = 150


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Expected a numeric precipitation measurement')
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid precipitation measurement')
    return float(value)


def ws90_rainfall(project_root, now):
    """Subtract fresh cumulative counters, with full coverage of the last 30 min.

    Historical and current logs are read only. Counter resets and coverage gaps
    make the source unavailable instead of inventing a zero rainfall amount.
    """
    directory = Path(project_root) / 'data/logs/weather_station'
    local_now = datetime.fromtimestamp(now, LOCAL_ZONE)
    days = {local_now.date(), (local_now - timedelta(hours=2)).date()}
    paths = [directory / ('weather_station.json.' + day.isoformat()) for day in sorted(days)]
    paths.append(directory / 'weather_station.json')
    rows = {}
    for path in paths:
        try:
            with path.open(encoding='utf-8') as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                        observed = datetime.strptime(row['last_updated'], STAMP_FORMAT).replace(tzinfo=LOCAL_ZONE).timestamp()
                        logged = datetime.strptime(row['timestamp'], STAMP_FORMAT).replace(tzinfo=LOCAL_ZONE).timestamp()
                        if now - WINDOW - MAX_AGE <= observed <= now and -30 <= logged - observed <= MAX_AGE:
                            rows[observed] = number(row['state']['precipitation_mm'])
                    except (ValueError, KeyError, TypeError):
                        continue
        except FileNotFoundError:
            continue
    times = sorted(rows)
    boundary = bisect.bisect_right(times, now - WINDOW) - 1
    if not times or boundary < 0 or now - times[-1] > MAX_AGE:
        raise ValueError('WS90 lacks a fresh measurement or the 30-minute baseline')
    selected = times[boundary:]
    if now - WINDOW - selected[0] > MAX_AGE:
        raise ValueError('WS90 30-minute baseline is stale')
    for a, b in zip(selected, selected[1:]):
        if b - a > MAX_AGE or rows[b] < rows[a]:
            raise ValueError('WS90 history has a gap or precipitation-counter reset')
    return {'source': 'WS90', 'amount_mm': rows[times[-1]] - rows[selected[0]],
            'window_start': now - WINDOW, 'window_end': now,
            'observed_at': times[-1], 'estimated': False}


def parse_open_meteo(payload, now):
    """Use two adjacent, completed 15-min bins. Reject nulls, bad units and age."""
    if payload.get('minutely_15_units', {}).get('precipitation') != 'mm':
        raise ValueError('Open-Meteo precipitation is not in millimetres')
    data = payload['minutely_15']
    times, values = data['time'], data['precipitation']
    if len(times) != len(values):
        raise ValueError('Open-Meteo timestamp/measurement lengths differ')
    rows = {}
    for t, value in zip(times, values):
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            raise ValueError('Open-Meteo has an invalid timestamp')
        if t <= now:
            rows[t] = value
    if not rows:
        raise ValueError('Open-Meteo has no completed interval')
    end = max(rows)
    if not 0 <= now - end <= 960 or end - 900 not in rows:
        raise ValueError('Open-Meteo lacks fresh, adjacent 15-minute intervals')
    amount = number(rows[end - 900]) + number(rows[end])
    return {'source': 'Open-Meteo', 'amount_mm': amount,
            'window_start': end - WINDOW, 'window_end': end,
            'observed_at': end, 'estimated': True}


class WeatherReader:
    def __init__(self, project_root, latitude, longitude, session=None):
        self.root = project_root
        self.latitude, self.longitude = latitude, longitude
        self.session = session or requests.Session()
        self.cached = None
        self.fetched_at = None

    def fallback(self, now):
        if self.cached is not None and 0 <= now - self.fetched_at < 300:
            try:
                return parse_open_meteo(self.cached, now)
            except (ValueError, KeyError, TypeError):
                pass  # A new quarter-hour may require a fresh response sooner.
        response = self.session.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': self.latitude, 'longitude': self.longitude,
            'minutely_15': 'precipitation', 'past_minutely_15': 6,
            'forecast_minutely_15': 1, 'timezone': 'UTC',
            'timeformat': 'unixtime', 'precipitation_unit': 'mm',
        }, timeout=(4, 8))
        response.raise_for_status()
        payload = response.json()
        result = parse_open_meteo(payload, now)
        self.cached, self.fetched_at = payload, now
        return result

    def read(self, now):
        errors = {}
        for name, read in [('WS90', lambda: ws90_rainfall(self.root, now)),
                           ('Open-Meteo', lambda: self.fallback(now))]:
            try:
                result = read()
                result['source_errors'] = errors
                return result
            except (OSError, ValueError, KeyError, TypeError, requests.RequestException) as error:
                errors[name] = str(error)
        return {'source': None, 'amount_mm': None, 'source_errors': errors}


def initial_state():
    return {'version': 1, 'rain_latched': False, 'recovery_required': False,
            'dry_since': None, 'last_check': None, 'source': None,
            'desired_on': None, 'plugs': {}, 'issues': {}}


def advance(previous, weather, now, *, restarted=False):
    """Return a new policy state; no IO or relay operations."""
    state = copy.deepcopy(previous)
    last = state.get('last_check')
    gap = last is not None and not 0 <= now - last <= MAX_CHECK_GAP
    changed_source = state.get('source') != weather.get('source')
    if restarted or gap or changed_source:
        state['dry_since'] = None
    if gap:
        state['recovery_required'] = True
    state.update(last_check=now, source=weather.get('source'), weather=weather)
    amount = weather.get('amount_mm')
    if weather.get('source') is None or amount is None:
        state.update(dry_since=None, recovery_required=True, desired_on=None,
                     mode='weather_unavailable')
        return state
    amount = number(amount)
    if amount > OFF_ABOVE_MM:
        state.update(rain_latched=True, recovery_required=True, dry_since=None)
    recovering = state['rain_latched'] or state['recovery_required']
    if recovering:
        if amount < RETURN_BELOW_MM:
            if state['dry_since'] is None:
                state['dry_since'] = now
            if now - state['dry_since'] >= RECOVERY_SECONDS:
                state.update(rain_latched=False, recovery_required=False, dry_since=None)
        else:
            state['dry_since'] = None
    if state['rain_latched']:
        state.update(desired_on=False, mode='rain_shutdown')
    elif state['recovery_required']:
        state.update(desired_on=None, mode='recovery_pending')
    else:
        state.update(desired_on=True, mode='normal')
    return state


def update_issue(state, key, message, now):
    """One notification per active incident, with failed deliveries retryable."""
    if message is None:
        previous = state['issues'].pop(key, None)
        if previous and not previous['sent']:
            state.setdefault('pending_notifications', []).append(
                dict(previous, key=key, resolved=True))
    elif key not in state['issues']:
        state['issues'][key] = {'message': message, 'opened_at': now,
                                'sent': False, 'last_attempt': None}


def off_expected(name, mac, now, path=STATE_PATH):
    """Watchdog suppression requires fresh controller intent and matching identity."""
    try:
        state = json.loads(Path(path).read_text(encoding='utf-8'))
        plug = state['plugs'][name]
        return (state['version'] == 1 and 0 <= now - state['last_check'] <= MAX_AGE
                and plug['mac'] == mac and
                (state.get('rain_latched') is True or state.get('recovery_required') is True))
    except (OSError, ValueError, KeyError, TypeError):
        return False
