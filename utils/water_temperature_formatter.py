"""Build per-cycle supply-water temperature series from raw heatmeter logs."""
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
            temperature = reading.get('flow_temperature_c')
            if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
                continue
            if not math.isfinite(temperature):
                continue
            series[str(cycle)][stamp] = {'timestamp': stamp, 'water_temp': temperature}
    return {cycle: [rows[stamp] for stamp in sorted(rows)] for cycle, rows in series.items()}
