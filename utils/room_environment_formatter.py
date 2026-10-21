"""Read-only room plot series; sensor assignments must come from room configuration.

Humidity retains the existing room measurement stream. This extra stream uses
the controller's selected temperature, mapped CO2/lux, observed occupancy and
the learned weekday/hour occupancy averages used by the scheduler.
"""
import json
from datetime import datetime
import math
from pathlib import Path

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'


def _number(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and (minimum is None or value >= minimum) else None


def _day_entries(entries, daystamp):
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            observed = datetime.strptime(entry.get('timestamp'), STAMP_FORMAT)
        except (TypeError, ValueError):
            continue
        if observed.strftime('%Y-%m-%d') == daystamp:
            yield observed, entry


def _sensor(sensors, *names):
    for name in names:
        if isinstance(name, str) and isinstance(sensors.get(name), dict):
            return sensors[name]
    return {}


def load_room_environment_sensors():
    """Reread editable room assignments every run; no dev database dependency."""
    path = Path(__file__).resolve().parent.parent / 'config' / 'nous_and_aqara_mapping.json'
    with path.open(encoding='utf-8-sig') as source:
        config = json.load(source)
    if config.get('schema_version') != 1 or not isinstance(config.get('rooms'), dict):
        raise ValueError('Invalid nous_and_aqara_mapping configuration')
    for room, metrics in config['rooms'].items():
        if not isinstance(metrics, dict):
            raise ValueError(f'Invalid room sensor assignments: {room}')
        for metric, sensors in metrics.items():
            if metric not in ('co2', 'lux') or not isinstance(sensors, list) or any(not isinstance(s, str) or not s.strip() for s in sensors):
                raise ValueError(f'Invalid {metric} sensor list for room {room}')
    return config['rooms']


def _average(sensors, names, key):
    values = [_number(_sensor(sensors, name).get(key)) for name in dict.fromkeys(names)]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def format_room_environment(air_entries, control_entries, daystamp, rooms, sensor_mapping=None, occupancy_patterns=None):
    """Never infer a Nous number or an Aqara location from a room number.

    Explicit assignments are {room: {'co2': [sensor_name], 'lux': [sensor_names]}}.
    Without an assignment, only the room's already configured sensor/presence
    device is eligible. Missing/invalid readings remain null, not vacancy/zero.
    """
    result = {str(room): {} for room in rooms}
    sensor_mapping = load_room_environment_sensors() if sensor_mapping is None else sensor_mapping
    for observed, entry in _day_entries(air_entries, daystamp):
        states = entry.get('states') or {}
        if not isinstance(states, dict):
            continue
        nous = states.get('nous') if isinstance(states.get('nous'), dict) else {}
        aqara = states.get('aqara') if isinstance(states.get('aqara'), dict) else {}
        for room, info in rooms.items():
            explicit = sensor_mapping.get(str(room), {})
            co2_names = explicit.get('co2', (info.get('sensor'),))
            lux_names = explicit.get('lux', (info.get('sensor'), info.get('pres')))
            reading = result[str(room)].setdefault(observed, {})
            reading.update(co2=_average(nous, co2_names, 'co2'), lux=_average(aqara, lux_names, 'lux'))
    for observed, entry in _day_entries(control_entries, daystamp):
        temperatures = entry.get('measured_temps')
        sources = entry.get('sensor_last_updated')
        if isinstance(temperatures, dict) and isinstance(sources, dict):
            for room in rooms:
                value = _number(temperatures.get(str(room)), minimum=None)
                try:
                    source_time = datetime.strptime(sources.get(str(room)), STAMP_FORMAT)
                except (TypeError, ValueError):
                    source_time = None
                if value is not None and source_time is not None and source_time <= observed:
                    if source_time.strftime('%Y-%m-%d') == daystamp:
                        result[str(room)].setdefault(source_time, {})['control_temp'] = value
                else:
                    result[str(room)].setdefault(observed, {})['control_temp'] = None
        occupancy = entry.get('occupancy')
        if not isinstance(occupancy, dict):
            continue
        for room in rooms:
            value = occupancy.get(str(room))
            result[str(room)].setdefault(observed, {})['occupancy'] = int(value) if isinstance(value, bool) else None
    if occupancy_patterns is not None:
        day = datetime.strptime(daystamp, '%Y-%m-%d')
        weekday = str(day.isoweekday())
        for room in rooms:
            profile = occupancy_patterns.get(str(room), {}).get(weekday, {})
            for hour in range(24):
                value = _number(profile.get(str(hour)))
                value = value if value is not None and value <= 1 else None
                # These are hourly averages: position each at the centre of its bin.
                result[str(room)].setdefault(day.replace(hour=hour, minute=30), {})['occupancy_average'] = value
                if hour in (0, 23):
                    edge = day if hour == 0 else day.replace(hour=23, minute=59, second=59)
                    result[str(room)].setdefault(edge, {})['occupancy_average'] = value
    return {room: [{'timestamp': observed.strftime(STAMP_FORMAT), **reading}
                   for observed, reading in sorted(rows.items())] for room, rows in result.items()}
