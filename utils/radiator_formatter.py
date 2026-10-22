"""Per-source radiator telemetry. Never infer a radiator/TRV pairing or operate devices."""
from datetime import datetime
import math

STAMP = '%Y-%m-%d-%H-%M-%S'


def _time(value):
    try:
        return datetime.strptime(value, STAMP)
    except (TypeError, ValueError):
        return None


def _number(value, lower, upper):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and lower <= value <= upper else None


def radiator_sources(mapping):
    groups = list(mapping.get('rooms', [])) + [mapping.get('unassigned', {})]
    return sorted({(probe['device'], probe['probe']) for group in groups for probe in group.get('probes', [])})


def format_radiator_temperatures(entries, daystamp, mapping):
    sources = radiator_sources(mapping)
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        observed = _time(entry.get('timestamp'))
        if observed is None or observed.strftime('%Y-%m-%d') != daystamp:
            continue
        values = {}
        for device, probe in sources:
            readings = entry.get(device)
            values[device + '/' + probe] = _number(readings.get(probe), -40, 125) if isinstance(readings, dict) else None
        result[entry['timestamp']] = {'timestamp': entry['timestamp'], 'probes': values}
    return [result[key] for key in sorted(result)]


def format_radiator_valves(entries, daystamp):
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        observed = _time(entry.get('timestamp'))
        states = entry.get('states')
        if observed is None or observed.strftime('%Y-%m-%d') != daystamp or not isinstance(states, dict):
            continue
        valves = {}
        for identifier, state in states.items():
            state = state if isinstance(state, dict) else {}
            seen = _time(state.get('lastseen'))
            fresh = seen is not None and -30 <= (observed - seen).total_seconds() <= 3600
            valves[str(identifier)] = _number(state.get('valve'), 0, 100) if fresh else None
        result[entry['timestamp']] = {'timestamp': entry['timestamp'], 'valves': valves}
    return [result[key] for key in sorted(result)]


def radiator_probe_snapshot(devices, observed_at):
    """Keep raw device/probe nesting for Firebase (slashes are not Firebase keys)."""
    return {'timestamp': observed_at, 'devices': {
        device: {name: _number(reading.get('temp'), -40, 125)
                 if not reading.get('errors') else None
                 for name, reading in details.get('peripherals', {}).items()}
        for device, details in devices.items()}}
