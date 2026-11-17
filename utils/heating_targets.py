"""Room target selection, independent of hardware and service initialization."""
import math
from datetime import datetime, timedelta


def request_temperature(value):
    """The form contains degrees Celsius, not an on/off flag."""
    if isinstance(value, bool):
        raise ValueError('Invalid requested temperature')
    temperature = float(value)
    if not math.isfinite(temperature):
        raise ValueError('Invalid requested temperature')
    return temperature


def warming_parameters(rows, controlled_rooms):
    if not rows or rows[0][0] != 'room_id':
        raise ValueError('Warming parameters require stable room_id keys')
    result = {}
    fields = ['a', 'b', 'start_factor', 'end_factor', 't_min', 't_max']
    has_off = len(rows[0]) == 8 and rows[0][7].strip().replace('_', '').lower() == 'toff'
    if len(rows[0]) != 7 and not has_off:
        raise ValueError('Optional warming-parameter column must be t_off')
    for row in rows[1:]:
        key = str(row[0]).strip()
        if key in result or key not in controlled_rooms:
            raise ValueError('Unexpected or duplicate warming-parameter room ID')
        if len(row) not in ((7, 8) if has_off else (7,)):
            raise ValueError('Incomplete warming-parameter row')
        result[key] = {field: float(value) for field, value in zip(fields, row[1:])}
        result[key]['t_off'] = (float(row[7]) if has_off and len(row) == 8 and str(row[7]).strip()
                                else result[key]['t_min'])
        if not all(math.isfinite(value) for value in result[key].values()):
            raise ValueError('Invalid warming-parameter coefficient')
    if set(result) != set(controlled_rooms):
        raise ValueError('Warming parameters must cover the controlled rooms')
    return result


def master_target_rooms(switch, rooms, scheduled_targets):
    """Keep existing switch precedence: schedule off, cycle, then room."""
    selected = {}
    if switch.get('system') != 1:
        return selected
    for room, info in rooms.items():
        if scheduled_targets.get(room) == -1:
            continue
        cycle_switch = switch['cycles'][str(info['cycle'])]
        if cycle_switch in (-1, 1):
            selected[room] = 'cycle_master_on' if cycle_switch == 1 else 'cycle_master_off'
        elif cycle_switch == 0 and switch['rooms'][room] in (-1, 1):
            selected[room] = 'room_master_on' if switch['rooms'][room] == 1 else 'room_master_off'
    return selected


def cycle_off_requests(rows):
    """Read current start/end/strong fields and historical duration-based responses."""
    result = []
    if not rows:
        return result
    headers = [str(value).strip().casefold() for value in rows[0]]
    aliases = {
        'cycle': ('cycle', 'melyik kört?'),
        'start_date': ('start_date', 'melyik napra?', 'melyik naptól?'),
        'start_hour': ('start_hour', 'hány órától?'),
        'duration': ('duration', 'mennyi időre? (órában)'),
        'end_date': ('end_date', 'melyik napig?'),
        'end_hour': ('end_hour', 'azon belül hány óráig?', 'hány óráig?'),
        'strong': ('strong', 'erős?'),
    }
    legacy = {'cycle': 1, 'start_date': 2, 'start_hour': 3, 'duration': 4}
    positions = {key: next((headers.index(label) for label in labels if label in headers), legacy.get(key))
                 for key, labels in aliases.items()}
    def at(row, key):
        index = positions[key]
        return str(row[index]).strip() if index is not None and index < len(row) else ''
    def when(day, hour, end=False):
        hour = int(hour)
        if not 0 <= hour <= (24 if end else 23):
            raise ValueError('Invalid cycle-off hour')
        return datetime.strptime(day, '%d/%m/%Y') + timedelta(hours=hour)
    for row in rows[1:]:
        if not row or not any(str(value).strip() for value in row):
            continue
        cycle = at(row, 'cycle')
        start = when(at(row, 'start_date'), at(row, 'start_hour'))
        if at(row, 'end_date') or at(row, 'end_hour'):
            end = when(at(row, 'end_date'), at(row, 'end_hour'), end=True)
        else:
            end = start + timedelta(hours=int(at(row, 'duration')))
        strong = at(row, 'strong') or '0'
        if cycle not in ('1', '2', '3', '4') or end <= start or strong not in ('0', '1'):
            raise ValueError('Invalid timed cycle-off request')
        result.append({'cycle': cycle, 'start': start, 'end': end, 'strong': int(strong)})
    return result


def cycle_off_active(requests, cycle, when):
    return any(request['cycle'] == str(cycle) and request['start'] <= when < request['end']
               for request in requests)


def cycle_off_mode(requests, cycle, when):
    """A strong request wins if soft and strong periods overlap."""
    active = [request['strong'] for request in requests
              if request['cycle'] == str(cycle) and request['start'] <= when < request['end']]
    return max(active) if active else None


def switches_with_timed_off(switch, requests, now):
    """Persistent cycle modes outrank the schedule; timed cycle modes outrank room modes."""
    effective = dict(switch, cycles=dict(switch['cycles']))
    timed_cycles = set()
    soft_cycles = set()
    for cycle, mode in effective['cycles'].items():
        timed_mode = cycle_off_mode(requests, cycle, now)
        if mode == 0 and timed_mode == 1:
            effective['cycles'][cycle] = -1
            timed_cycles.add(str(cycle))
        elif mode == 0 and timed_mode == 0:
            soft_cycles.add(str(cycle))
    return effective, timed_cycles, soft_cycles
