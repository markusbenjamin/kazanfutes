"""Local, stable-room-ID weekly baseline for the staged room-ID release.

No network access or automatic replacement of the administrator's JSON file.
This module is inactive until the v2 scheduler is wired to it at rollout.
"""
import json
import math
import re
from pathlib import Path


def validate_weekly_cycle(config):
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise ValueError('Unsupported weekly cycle schema')
    rooms = config.get('rooms')
    if not isinstance(rooms, dict) or not rooms:
        raise ValueError('Weekly cycle needs room entries')
    for room, days in rooms.items():
        if not isinstance(room, str) or not re.fullmatch(r'[1-9][0-9]*', room):
            raise ValueError(f'Invalid weekly room ID: {room}')
        if not isinstance(days, dict) or set(days) != {str(n) for n in range(1, 8)}:
            raise ValueError(f'Room {room} needs ISO weekdays 1 through 7')
        for day, values in days.items():
            if not isinstance(values, list) or len(values) != 24:
                raise ValueError(f'Room {room}, weekday {day} needs 24 hourly values')
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
                raise ValueError(f'Room {room}, weekday {day} has invalid presence values')
    return config


def load_weekly_cycle(path):
    with Path(path).open(encoding='utf-8-sig') as source:
        return validate_weekly_cycle(json.load(source))


def weekly_presence(config, room_id, iso_weekday, hour):
    if type(iso_weekday) is not int or not 1 <= iso_weekday <= 7:
        raise ValueError('Weekday must be an ISO weekday from 1 through 7')
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError('Hour must be from 0 through 23')
    # A missing scheduled room is a configuration error, not zero occupancy.
    return config['rooms'][str(room_id)][str(iso_weekday)][hour]
