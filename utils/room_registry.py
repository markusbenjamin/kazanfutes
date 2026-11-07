"""Validated room identities and presentation names for the v2 release.

Pure file/data helpers: importing this module does not contact or operate devices.
The registry Sheet owns names; definitions own physical/control associations.
"""
import copy
import json
import math
import re
from pathlib import Path

from utils.room_source_policy import averaging_sources


def room_id(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError(f'Invalid stable room ID: {value}')
    return value


def validate_definitions(document):
    if document.get('schema_version') != 2 or not isinstance(document.get('rooms'), dict):
        raise ValueError('Unsupported room definition schema')
    for key, info in document['rooms'].items():
        room_id(key)
        if not isinstance(info.get('included'), bool) or not isinstance(info.get('controlled'), bool):
            raise ValueError(f'Room {key} needs explicit inclusion/control flags')
        if info.get('cycle') is not None and info['cycle'] not in ('1', '2', '3', '4'):
            raise ValueError(f'Room {key} has an invalid heating cycle')
        if info['controlled'] and (not info['included'] or info.get('cycle') is None):
            raise ValueError(f'Controlled room {key} must be included and have a cycle')
        if info.get('valve_mode') not in ('trv', 'unrestricted', 'none'):
            raise ValueError(f'Room {key} has an unresolved valve mode')
        if info['controlled'] and info['valve_mode'] == 'none':
            raise ValueError(f'Controlled room {key} has no heating output')
        for field in ('temperature_sensors', 'presence_sensors', 'trv_ids', 'co2_sensors', 'lux_sensors'):
            values = info.get(field)
            if values is not None and (not isinstance(values, list)
                    or any(not isinstance(item, str) or not item.strip() for item in values)):
                raise ValueError(f'Room {key} has an invalid {field} list')
        if info['valve_mode'] == 'trv' and not info.get('trv_ids'):
            raise ValueError(f'Room {key} needs TRV identities')
        if len(info.get('co2_sensors') or []) > 1:
            raise ValueError(f'Room {key}: select one CO2 source; Nous readings are not averaged')
    return document


def registry_from_rows(rows, expected_ids):
    if not rows or [str(cell).strip() for cell in rows[0][:2]] != ['room_id', 'display_name']:
        raise ValueError('Registry header must be room_id,display_name')
    names = {}
    for row in rows[1:]:
        if not row or all(not str(cell).strip() for cell in row):
            continue
        if len(row) < 2:
            raise ValueError('Registry row has no display name')
        key, name = room_id(str(row[0]).strip()), str(row[1]).strip()
        if key in names or not name:
            raise ValueError(f'Duplicate room ID or empty name: {key}')
        names[key] = {'display_name': name}
    if set(names) != set(expected_ids):
        raise ValueError('Registry IDs must match the registered room definitions')
    # Repeated display names are explicitly allowed.
    return {'schema_version': 1, 'rooms': names}


def validate_registry(registry, expected_ids):
    rows = [['room_id', 'display_name']]
    if registry.get('schema_version') != 1 or not isinstance(registry.get('rooms'), dict):
        raise ValueError('Unsupported room registry schema')
    rows.extend([key, value.get('display_name', '')] for key, value in registry['rooms'].items())
    return registry_from_rows(rows, expected_ids)


def load_room_configuration(root):
    root = Path(root)
    with (root / 'config/room_definitions.json').open(encoding='utf-8-sig') as source:
        definitions = validate_definitions(json.load(source))
    with (root / 'system/room_registry.json').open(encoding='utf-8-sig') as source:
        registry = validate_registry(json.load(source), definitions['rooms'])
    return definitions, registry


def runtime_rooms(definitions, registry, controlled_only=False):
    registry = validate_registry(registry, definitions['rooms'])
    rooms = {}
    for key, original in definitions['rooms'].items():
        if not original['included'] or (controlled_only and not original['controlled']):
            continue
        info = copy.deepcopy(original)
        info['name'] = registry['rooms'][key]['display_name']
        info['svg_target'] = 'room_' + key
        info['temperature_sensors'] = averaging_sources(info.get('temperature_sensors') or [])
        info['sensor'] = next(iter(info['temperature_sensors']), False)
        info['pres'] = next(iter(info.get('presence_sensors') or []), False)
        info['thermostats'] = (';'.join(info['trv_ids']) if info['valve_mode'] == 'trv'
                               else info['valve_mode'] == 'unrestricted')
        rooms[key] = info
    return rooms


def effective_setup(hardware_setup, definitions, registry):
    """Build an in-memory room overlay, preserving every non-room hardware value."""
    result = copy.deepcopy(hardware_setup)
    result['rooms'] = runtime_rooms(definitions, registry)
    for cycle, info in result['cycles'].items():
        info['rooms'] = [key for key, room in result['rooms'].items() if room.get('cycle') == str(cycle)]
    return result


def read_request_rows(rows, controlled_ids):
    """Read only the new explicit room_id column; visible labels are audit text."""
    if not rows or 'room_id' not in rows[0]:
        raise ValueError('Request response Sheet needs the room_id column')
    position = rows[0].index('room_id')
    result = []
    for row in rows[1:]:
        if not row or not any(str(value).strip() for value in row):
            continue
        if len(row) <= position or len(row) < 6:
            raise ValueError('Request row is missing required fields')
        key = room_id(str(row[position]).strip())
        if key not in controlled_ids:
            # Archived/excluded requests cannot grant control eligibility.
            continue
        result.append({'google_timestamp': row[0], 'room_id': key, 'date': row[2],
                       'hour_of_day': row[3], 'duration': row[4], 'on': row[5]})
    return result


def request_marker_rows(rows, controlled_ids):
    fields = ['google_timestamp', 'room_id', 'date', 'hour_of_day', 'duration', 'on']
    return [[command[field] for field in fields] for command in read_request_rows(rows, controlled_ids)]


def room_measurement_rows(entries, key):
    result = []
    for entry in entries:
        reading = entry.get(str(key)) if isinstance(entry, dict) else None
        if not isinstance(reading, dict):
            continue
        def number(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        temperature = reading.get('temp')
        humidity = reading.get('hum')
        # The room's calculated stream, including its existing TRV fallback.
        if number(temperature):
            temperature, stamp = temperature / 100, reading.get('last_updated')
        else:
            temperature = reading.get('thermostat_temp')
            stamp = reading.get('thermostat_last_updated') or reading.get('humidity_last_updated')
        if not stamp or not (number(temperature) or number(humidity)):
            continue
        row = {'timestamp': stamp, 'temp': temperature if number(temperature) else None,
               'hum': humidity / 100 if number(humidity) else None}
        if not result or row != result[-1]:
            result.append(row)
    return result


def fresh_sensor_average(names, sensor_readings, expiry_minutes, now):
    """Use only assigned, non-Nous, finite samples within the freshness window."""
    values, stamps = [], []
    for name in averaging_sources(names):
        reading = sensor_readings.get(name) or {}
        stamp = reading.get('last_updated')
        if stamp is None or not -5 <= (now - stamp).total_seconds() <= expiry_minutes * 60:
            continue
        value = reading.get('temp')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        values.append(value)
        stamps.append(stamp)
    return (sum(values) / len(values), min(stamps)) if values else (None, None)
