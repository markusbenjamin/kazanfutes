"""Time-weighted room tracking KPIs from the control service's recorded inputs.

No device access or control changes. Commands and setpoints are held as steps,
never interpolated. Unknown/stale observations do not become good performance.
"""
from datetime import datetime, timedelta
import math

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
QUADRANTS = ('below_on', 'above_on', 'below_off', 'above_off')


def _stamp(value):
    try:
        return datetime.strptime(value, STAMP_FORMAT)
    except (TypeError, ValueError):
        return None


def _number(value):
    return value if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) else None


def format_room_control_kpis(entries, daystamp, rooms, end_time=None,
                             tolerance_c=.5, max_hold_seconds=180,
                             max_sensor_age_seconds=3600):
    """Report MAE/bias while circulation is commanded on, plus all-state comfort.

    Use the already calculated measured_temps and the same set_temps that the
    ordinary room plot displays. sensor_last_updated bounds sensor freshness.
    The on/off distinction is pump_votes, not room demand or measured heat flow.
    end_time limits today's unfinished day; archived days default to midnight.
    """
    if tolerance_c < 0 or max_hold_seconds <= 0 or max_sensor_age_seconds <= 0:
        raise ValueError('Invalid room KPI tolerance or freshness limits')
    start = datetime.strptime(daystamp, '%Y-%m-%d')
    end = min(start + timedelta(days=1), max(start, end_time or start + timedelta(days=1)))
    controlled = {str(room): info for room, info in rooms.items() if info.get('controlled') and info.get('cycle') is not None}
    events = {start: {}, end: {}}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        observed = _stamp(entry.get('timestamp'))
        if observed is None or not start - timedelta(seconds=max_hold_seconds) <= observed <= end:
            continue
        update = events.setdefault(observed, {})
        for field in ('measured_temps', 'set_temps', 'pump_votes', 'sensor_last_updated'):
            if isinstance(entry.get(field), dict):
                update[field] = entry[field]

    stats = {room: {'valid_seconds': 0., 'heating_seconds': 0., 'comfort_seconds': 0.,
                    'absolute_error_on_kh': 0., 'signed_error_on_kh': 0.,
                    'quadrant_seconds': {key: 0. for key in QUADRANTS}}
             for room in controlled}
    temperatures, targets, commands = {}, {}, {}

    def integrate(left, right):
        for room, info in controlled.items():
            temperature = temperatures.get(room)
            target = targets.get(room)
            command = commands.get(str(info['cycle']))
            if temperature is None or target is None or command is None:
                continue
            valid_end = min(right, temperature[1], target[1], command[1])
            seconds = (valid_end - left).total_seconds()
            if seconds <= 0:
                continue
            error = temperature[0] - target[0]
            row = stats[room]
            row['valid_seconds'] += seconds
            within = abs(error) <= tolerance_c + 1e-9
            if within:
                row['comfort_seconds'] += seconds
            else:
                quadrant = ('below' if error < 0 else 'above') + ('_on' if command[0] else '_off')
                row['quadrant_seconds'][quadrant] += seconds
            if command[0]:
                row['heating_seconds'] += seconds
                row['absolute_error_on_kh'] += abs(error) * seconds / 3600
                row['signed_error_on_kh'] += error * seconds / 3600

    cursor = start
    for observed, update in sorted(events.items()):
        if observed > cursor:
            integrate(cursor, observed)
            cursor = observed
        expiry = observed + timedelta(seconds=max_hold_seconds)
        if 'measured_temps' in update:
            sensor_stamps = update.get('sensor_last_updated', {})
            for room in controlled:
                value = _number(update['measured_temps'].get(room))
                source_time = _stamp(sensor_stamps.get(room))
                fresh = source_time is not None and -30 <= (observed - source_time).total_seconds() <= max_sensor_age_seconds
                temperatures[room] = (value, min(expiry, source_time + timedelta(seconds=max_sensor_age_seconds))) if value is not None and fresh else None
        if 'set_temps' in update:
            for room in controlled:
                value = _number(update['set_temps'].get(room))
                targets[room] = (value, expiry) if value is not None and value >= 0 else None
        if 'pump_votes' in update:
            for cycle in {str(info['cycle']) for info in controlled.values()}:
                value = update['pump_votes'].get(cycle)
                commands[cycle] = (int(value), expiry) if isinstance(value, (bool, int)) and value in (0, 1) else None

    elapsed = (end - start).total_seconds()
    for row in stats.values():
        heating_hours = row['heating_seconds'] / 3600
        row['mae_on_c'] = row['absolute_error_on_kh'] / heating_hours if heating_hours else None
        row['bias_on_c'] = row['signed_error_on_kh'] / heating_hours if heating_hours else None
        row['comfort_pct'] = 100 * row['comfort_seconds'] / row['valid_seconds'] if row['valid_seconds'] else None
        row['coverage_pct'] = 100 * row['valid_seconds'] / elapsed if elapsed else 0.
    return {'schema_version': 1, 'day': daystamp, 'observed_until': end.strftime(STAMP_FORMAT),
            'tolerance_c': tolerance_c, 'max_hold_seconds': max_hold_seconds,
            'max_sensor_age_seconds': max_sensor_age_seconds, 'state_source': 'cycle_command', 'rooms': stats}
