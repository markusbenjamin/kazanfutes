"""Read-only boiler diagnostic: plug power first, water temperature as fallback."""
import json
import math
from datetime import datetime
from pathlib import Path

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
MAX_SNAPSHOT_BYTES = 65536


def _heating_enabled(switch):
    if not isinstance(switch, dict) or switch.get('system') != 1:
        return False
    cycles = switch.get('cycles')
    return isinstance(cycles, dict) and any(mode in (0, 1) for mode in cycles.values())


def _fresh_snapshot(snapshot, now, max_age_seconds):
    if not isinstance(snapshot, dict):
        return False
    if (isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float))
            or not math.isfinite(max_age_seconds) or max_age_seconds <= 0):
        return False
    try:
        observed = datetime.strptime(snapshot.get('timestamp'), STAMP_FORMAT)
        age = (now - observed).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return False
    return 0 <= age <= max_age_seconds


def boiler_error_from_power(switch, snapshot, now, max_age_seconds=90):
    """Return None only when plug power is unavailable and water must be checked."""
    if not _heating_enabled(switch):
        return ''
    if (not _fresh_snapshot(snapshot, now, max_age_seconds)
            or snapshot.get('name') != 'boiler_1_plug'
            or snapshot.get('reachable') is not True or snapshot.get('collection_error')):
        return None
    measurements = snapshot.get('measurements')
    power = measurements.get('power_w') if isinstance(measurements, dict) else None
    if (isinstance(power, bool) or not isinstance(power, (int, float))
            or not math.isfinite(power) or power < 0):
        return None
    return 'kazán hiba!' if power < 20 else ''


def boiler_error_from_snapshot(switch, snapshot, meter_mapping, now, max_age_seconds=90):
    """Diagnose enabled circuits only; unavailable data is never a boiler fault."""
    if not _heating_enabled(switch) or not _fresh_snapshot(snapshot, now, max_age_seconds):
        return ''
    cycles = switch['cycles']
    states = snapshot.get('states')
    if not isinstance(states, dict):
        return ''
    temperatures = []
    for cycle, meter in meter_mapping.items():
        # Switch 0 means automatic/enabled; -1 means disabled.
        if cycles.get(str(cycle)) not in (0, 1):
            continue
        reading = states.get(str(meter), states.get(meter))
        if not isinstance(reading, dict):
            continue
        temperature = reading.get('flow_temperature_c')
        # Match the existing heat-delivery validator's usable water range.
        if (not isinstance(temperature, bool) and isinstance(temperature, (int, float))
                and math.isfinite(temperature) and 0 < temperature < 100):
            temperatures.append(temperature)
    return 'kazán hiba!' if temperatures and max(temperatures) < 28 else ''


def _latest_snapshot(path, field, value=None):
    """Bound the local read; ignore a partial final line and other devices' rows."""
    try:
        with path.open('rb') as source:
            source.seek(0, 2)
            offset = max(0, source.tell() - MAX_SNAPSHOT_BYTES)
            source.seek(offset)
            if offset:
                source.readline()  # Discard a potentially truncated first record.
            lines = source.read(MAX_SNAPSHOT_BYTES).splitlines()
        for line in reversed(lines):
            try:
                snapshot = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(snapshot, dict) and field in snapshot and (value is None or snapshot[field] == value):
                return snapshot
    except OSError:
        pass
    return None


def read_boiler_error(root, switch, now):
    """Prefer fresh boiler_1_plug power; fall back only when it is unavailable.

    Local bounded reads only: no network calls or device commands. The newest
    complete observation wins, including one reporting an unreachable plug.
    """
    if not _heating_enabled(switch):
        return ''
    root = Path(root)
    try:
        config = json.loads((root / 'config/heating_monitor.json').read_text(encoding='utf-8'))
        if not isinstance(config, dict):
            config = {}
    except (OSError, ValueError):
        config = {}
    max_age_seconds = config.get('reading_max_age_seconds', 90)
    power = _latest_snapshot(root / 'data/logs/boilers_power/boiler_plugs.json', 'name', 'boiler_1_plug')
    error = boiler_error_from_power(switch, power, now, max_age_seconds)
    if error is not None:
        return error
    try:
        mapping = {str(cycle): info['meter'] for cycle, info in config['cycles'].items()}
        water = _latest_snapshot(root / 'data/logs/heat_delivery/heatmeters_state.json', 'states')
        return boiler_error_from_snapshot(switch, water, mapping, now, max_age_seconds)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return ''
