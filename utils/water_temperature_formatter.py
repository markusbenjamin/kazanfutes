"""Build per-cycle supply/return water temperatures from raw heatmeter logs."""
import math
from datetime import datetime


def format_cycle_water_temperatures(entries, daystamp, meter_mapping):
    day = datetime.strptime(daystamp, '%Y-%m-%d').date()
    series = {str(cycle): {} for cycle in meter_mapping}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stamp = entry.get('timestamp')
        try:
            observed = datetime.strptime(stamp, '%Y-%m-%d-%H-%M-%S')
        except (TypeError, ValueError):
            continue
        if observed.date() != day:
            continue
        states = entry.get('states')
        if not isinstance(states, dict):
            continue
        for cycle, meter in meter_mapping.items():
            reading = states.get(str(meter), states.get(meter))
            if not isinstance(reading, dict):
                continue
            row = {'timestamp': stamp}
            for key, source in [('water_temp', 'flow_temperature_c'), ('return_temp', 'return_temperature_c')]:
                temperature = reading.get(source)
                valid = not isinstance(temperature, bool) and isinstance(temperature, (int, float)) and math.isfinite(temperature)
                row[key] = temperature if valid else None
            # Explicit invalid values break only the affected curve, never become zero.
            series[str(cycle)][stamp] = row
    return {cycle: [rows[stamp] for stamp in sorted(rows)] for cycle, rows in series.items()}
