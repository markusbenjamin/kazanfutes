"""Per-cycle instantaneous thermal power (kW) and flow from heatmeter logs."""
from datetime import datetime
import math

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def format_cycle_heat_delivery(entries, daystamp, meter_mapping):
    day = datetime.strptime(daystamp, '%Y-%m-%d')
    observations = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            observed = datetime.strptime(entry.get('timestamp'), STAMP_FORMAT)
        except (TypeError, ValueError):
            continue
        if observed.date() == day.date() and isinstance(entry.get('states'), dict):
            observations[observed] = entry['states']

    result = {}
    for cycle, meter in meter_mapping.items():
        rows = []
        for observed, states in sorted(observations.items()):
            reading = states.get(str(meter), states.get(meter))
            reading = reading if isinstance(reading, dict) else {}
            watts = _number(reading.get('power_w'))
            flow = _number(reading.get('volume_flow_m3h'))
            rows.append({
                'timestamp': observed.strftime(STAMP_FORMAT),
                'power_kw': watts / 1000 if watts is not None else None,
                'flow_m3h': flow,
            })
        result[str(cycle)] = rows
    return result
