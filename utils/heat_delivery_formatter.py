"""Per-cycle thermal power, flow and estimated daily delivered energy.

Integrate measured watts, not the raw cumulative counter with unresolved
units/jumps. Never integrate through invalid readings or gaps over 3 minutes.
Positive power must be supported by the measured flow and temperature drop;
corrupt registers are missing observations, never clipped replacement values.
"""
from datetime import datetime
import math

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
WATER_W_PER_M3H_K = 1163.0


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _temperature(value):
    value = _number(value)
    return value if value is not None and 0 < value < 100 else None


def _validated_power(reading, min_flow_m3h, power_tolerance_w, power_tolerance_fraction):
    watts = _number(reading.get('power_w'))
    # A measured zero remains valid without inventing temperature/flow values.
    if watts is None or watts == 0:
        return watts
    flow = _number(reading.get('volume_flow_m3h'))
    supply = _temperature(reading.get('flow_temperature_c'))
    returned = _temperature(reading.get('return_temperature_c'))
    if flow is None or flow <= min_flow_m3h or supply is None or returned is None or supply <= returned:
        return None
    expected = WATER_W_PER_M3H_K * flow * (supply - returned)
    tolerance = max(power_tolerance_w, power_tolerance_fraction * expected)
    if not math.isfinite(expected) or abs(watts - expected) > tolerance:
        return None
    return watts


def heatmeter_live_snapshot(readings, observed_at):
    """Publish the same corroborated power used in charts, plus return temperature."""
    snapshot = {'last_updated': observed_at}
    for meter, reading in readings.items():
        reading = reading if isinstance(reading, dict) else {}
        watts = _validated_power(reading, 0.005, 2000, 0.3)
        snapshot[str(meter)] = {
            'temp': _temperature(reading.get('flow_temperature_c')),
            'return_temp': _temperature(reading.get('return_temperature_c')),
            'flow': _number(reading.get('volume_flow_m3h')),
            'power': watts / 1000 if watts is not None else None,
        }
    return snapshot


def format_cycle_heat_delivery(entries, daystamp, meter_mapping, max_gap_seconds=180, *,
                               min_flow_m3h=0.005, power_tolerance_w=2000,
                               power_tolerance_fraction=0.3):
    """Integrate corroborated reported watts, with conservative missing-data gaps.

    Flow * (supply - return) * 1163 independently checks positive reported watts.
    The 2 kW / 30% tolerance accommodates rounded and asynchronous registers,
    matching the demand formatter's consistency check. No arbitrary boiler-size
    ceiling or moving-average clipping suppresses corroborated heating peaks.
    """
    for name, value, zero_allowed in [('max_gap_seconds', max_gap_seconds, False),
                                      ('min_flow_m3h', min_flow_m3h, True),
                                      ('power_tolerance_w', power_tolerance_w, False),
                                      ('power_tolerance_fraction', power_tolerance_fraction, False)]:
        if _number(value) is None or (not zero_allowed and value == 0):
            raise ValueError(f'{name} must be finite and ' + ('nonnegative' if zero_allowed else 'positive'))
    day = datetime.strptime(daystamp, '%Y-%m-%d')
    observations = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            observed = datetime.strptime(entry.get('timestamp'), STAMP_FORMAT)
        except (TypeError, ValueError):
            continue
        if observed.date() == day.date():
            # Keep malformed observations as explicit breaks; last duplicate wins.
            observations[observed] = entry.get('states') if isinstance(entry.get('states'), dict) else {}

    result = {}
    for cycle, meter in meter_mapping.items():
        rows, previous, total, has_power, partial = [], None, 0.0, False, False
        for observed, states in sorted(observations.items()):
            reading = states.get(str(meter), states.get(meter))
            reading = reading if isinstance(reading, dict) else {}
            watts = _validated_power(reading, min_flow_m3h, power_tolerance_w, power_tolerance_fraction)
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
                previous, has_power = (observed, watts), True
            rows.append({
                'timestamp': observed.strftime(STAMP_FORMAT),
                'power_kw': watts / 1000 if watts is not None else None,
                'flow_m3h': flow,
                'energy_kwh': round(total, 9) if has_power else None,
                'energy_partial': partial,
            })
        result[str(cycle)] = rows
    return result
