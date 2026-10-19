"""Pure dashboard formatting; never query or operate boiler hardware."""

from datetime import datetime, time
import math

BOILER_PLUG_NAMES = ('boiler_1_plug', 'boiler_2_plug')
STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'


def _stamp(value):
    try:
        return datetime.strptime(value, STAMP_FORMAT)
    except (TypeError, ValueError):
        return None


def _power(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def boiler_power_snapshot(devices, observed_at):
    """Only fresh successful observations carry power, including genuine zero W."""
    result = {name: {'timestamp': observed_at, 'reachable': False, 'power_w': None}
              for name in BOILER_PLUG_NAMES}
    for device in devices:
        name = device.get('name')
        if name not in result:
            continue
        facts = device.get('facts') or {}
        reachable = facts.get('reachable') is True
        stamp = observed_at
        try:
            stamp = datetime.fromisoformat(facts['last_seen_at']).astimezone().strftime(STAMP_FORMAT)
        except (KeyError, TypeError, ValueError):
            pass
        result[name] = {
            'timestamp': stamp,
            'reachable': reachable,
            'power_w': _power((facts.get('measurements') or {}).get('power_w')) if reachable else None,
        }
    return result


def format_boiler_power(entries, daystamp):
    day = datetime.strptime(daystamp, '%Y-%m-%d').date()
    series = {name: {} for name in BOILER_PLUG_NAMES}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('name') not in series:
            continue
        observed = _stamp(entry.get('timestamp'))
        if observed is None or observed.date() != day:
            continue
        power = _power((entry.get('measurements') or {}).get('power_w')) if entry.get('reachable') is True else None
        series[entry['name']][entry['timestamp']] = {'timestamp': entry['timestamp'], 'power_w': power}
    return {name: [rows[stamp] for stamp in sorted(rows)] for name, rows in series.items()}


def format_boiler_commands(commands, daystamp, now=None):
    """Executed controller commands, shared by both plugs; not plug relay states.

    Carry the last known pre-midnight state into the requested day. Unknown
    history stays unknown; an absent command is not an OFF command.
    """
    day = datetime.strptime(daystamp, '%Y-%m-%d').date()
    start = datetime.combine(day, time.min)
    end = min(now or datetime.now(), datetime.combine(day, time(23, 59, 59)))
    if end < start:
        return []
    events = {}
    for command in commands:
        if not isinstance(command, dict) or command.get('device') != 'boiler' or command.get('executed') is not True:
            continue
        observed = _stamp(command.get('execution_timestamp'))
        setting = command.get('setting')
        if observed is None or observed > end or setting not in (0, 1):
            continue
        events[observed] = int(setting)
    previous = None
    result = []
    for observed, setting in sorted(events.items()):
        if observed <= start:
            previous = setting
            continue
        if not result and previous is not None:
            result.append({'timestamp': start.strftime(STAMP_FORMAT), 'command_on': previous})
        if setting != previous:
            result.append({'timestamp': observed.strftime(STAMP_FORMAT), 'command_on': setting})
        previous = setting
    if previous is None:
        return []
    if not result:
        result.append({'timestamp': start.strftime(STAMP_FORMAT), 'command_on': previous})
    end_stamp = end.strftime(STAMP_FORMAT)
    if result[-1]['timestamp'] != end_stamp:
        result.append({'timestamp': end_stamp, 'command_on': previous})
    return result
