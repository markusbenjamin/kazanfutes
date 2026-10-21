"""Per-cycle flow and estimated daily delivered heat from logged heatmeter power.

The raw energy_kwh counter is deliberately not used: existing logs contain
counter jumps and an unresolved unit discrepancy. Integrate the measured W
over observed intervals instead; never integrate through missing/long gaps.
"""
from datetime import datetime
import math

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def format_cycle_heat_delivery(entries, daystamp, meter_mapping, max_gap_seconds=180):
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
        rows, previous, total, partial = [], None, 0.0, False
        for observed, states in sorted(observations.items()):
            reading = states.get(str(meter), states.get(meter))
            reading = reading if isinstance(reading, dict) else {}
            watts = _number(reading.get('power_w'))
            flow = _number(reading.get('volume_flow_m3h'))
            if not rows and (observed - day).total_seconds() > max_gap_seconds:
                partial = True
            if watts is None:
                partial, previous = True, None
            else:
                if previous is not None:
                    seconds = (observed - previous[0]).total_seconds()
                    if seconds <= max_gap_seconds:
                        total += (previous[1] + watts) / 2 * seconds / 3600000
                    else:
                        partial = True
                previous = (observed, watts)
            rows.append({
                'timestamp': observed.strftime(STAMP_FORMAT),
                'energy_kwh': round(total, 9) if watts is not None else None,
                'energy_partial': partial,
                'flow_m3h': flow,
            })
        result[str(cycle)] = rows
    return result
