"""Read-only boiler diagnostic from the latest local heatmeter snapshot."""
import json
import math
from datetime import datetime
from pathlib import Path

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
MAX_SNAPSHOT_BYTES = 65536


def boiler_error_from_snapshot(switch, snapshot, meter_mapping, now, max_age_seconds=90):
    """Diagnose enabled circuits only; unavailable data is never a boiler fault."""
    if not isinstance(switch, dict) or switch.get('system') != 1:
        return ''
    cycles = switch.get('cycles')
    if not isinstance(cycles, dict) or not isinstance(snapshot, dict):
        return ''
    if (isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float))
            or not math.isfinite(max_age_seconds) or max_age_seconds <= 0):
        return ''
    try:
        observed = datetime.strptime(snapshot.get('timestamp'), STAMP_FORMAT)
        age = (now - observed).total_seconds()
    except (TypeError, ValueError, OverflowError):
        return ''
    if not 0 <= age <= max_age_seconds:
        return ''
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


def read_boiler_error(root, switch, now):
    """Bounded local read, with no network calls or device commands.

    A partial final NDJSON line is ignored. Only the latest complete snapshot
    is evaluated, so older warm readings cannot mask a newer cold snapshot.
    """
    if not isinstance(switch, dict) or switch.get('system') != 1:
        return ''
    root = Path(root)
    try:
        config = json.loads((root / 'config/heating_monitor.json').read_text(encoding='utf-8'))
        mapping = {str(cycle): info['meter'] for cycle, info in config['cycles'].items()}
        path = root / 'data/logs/heat_delivery/heatmeters_state.json'
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
            if isinstance(snapshot, dict) and 'states' in snapshot:
                return boiler_error_from_snapshot(
                    switch, snapshot, mapping, now, config['reading_max_age_seconds'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return ''
