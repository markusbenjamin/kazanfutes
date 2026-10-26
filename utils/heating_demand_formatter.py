"""Water-side demand at a causal, inferred common supply-temperature plateau.

This is the thermal power needed to lift the currently returning flows to the
inferred target, not burner output. DHW, buffer charging and losses are absent.
Stable, positively heat-delivering flows supply target evidence; idle circuit
temperatures never contribute. An upper quantile of recent sustained plateaus
avoids following every burner-cycle trough. It is not a measured boiler setpoint.
"""
from collections import deque
from datetime import datetime, timedelta
import math
from statistics import median

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
WATER_KW_PER_M3H_K = 1.163


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _temperature(value):
    value = _number(value)
    return value if value is not None and 0 < value < 100 else None


def _quantile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def format_heating_demand(entries, daystamp, meter_mapping, *,
                          min_flow_m3h=0.005, target_temperature_c=None,
                          target_window_seconds=7200, plateau_duration_seconds=300,
                          plateau_tolerance_c=2.0, plateau_quantile=0.9,
                          min_plateau_temperature_c=30.0, min_plateau_delta_c=3.0,
                          max_gap_seconds=180, power_tolerance_kw=2.0,
                          power_tolerance_fraction=0.3):
    """Return one demand row per heatmeter observation in the requested day.

    Include preceding-day entries to preserve the causal target at midnight.
    ``min_flow_m3h`` may be a scalar or a per-cycle mapping. Flow at or below
    that threshold is inactive, regardless of temperature availability. Missing
    flow is unknown, never inactive. A missing active return makes total demand
    unknown; an active supply is needed for plateau detection, not for demand.

    Targets are the upper quantile of five-minute plateau medians in the trailing
    two hours by default. There is no nominal-temperature fallback. A configured
    target overrides inference explicitly. Each plateau must contain at least
    four observations, remain within the temperature tolerance, have positive
    supply-return difference, and contain no gap over ``max_gap_seconds``.

    Where reported watts are available, a substantial disagreement with positive
    flow-derived delivered heat invalidates that circuit for both inference and
    demand. This catches corrupt flow as well as corrupt power without deciding
    which register is right. The tolerances allow rounding/asynchronous updates.

    Per-cycle values are signed heat requirements (a hotter return can offset
    another circuit); only the aggregate is clamped to nonnegative heating power.
    No daily energy integral is emitted: demand is counterfactual, not delivery.
    """
    positive_options = (target_window_seconds, plateau_duration_seconds,
                        plateau_tolerance_c, max_gap_seconds, power_tolerance_kw,
                        power_tolerance_fraction)
    if any(_number(v) is None or v <= 0 for v in positive_options):
        raise ValueError('window, duration, tolerance and gap must be positive')
    if _number(plateau_quantile) is None or not 0 <= plateau_quantile <= 1:
        raise ValueError('plateau_quantile must be between zero and one')
    if _temperature(min_plateau_temperature_c) is None:
        raise ValueError('invalid minimum plateau temperature')
    if _number(min_plateau_delta_c) is None or min_plateau_delta_c <= 0:
        raise ValueError('minimum plateau temperature difference must be positive')
    if target_temperature_c is not None and _temperature(target_temperature_c) is None:
        raise ValueError('configured target must be between zero and 100 C')
    mapping = {str(cycle): meter for cycle, meter in meter_mapping.items()}
    if not mapping or len(set(str(meter) for meter in mapping.values())) != len(mapping):
        raise ValueError('each cycle must map to a distinct meter')
    thresholds = {cycle: _number(min_flow_m3h.get(cycle)) if isinstance(min_flow_m3h, dict)
                  else _number(min_flow_m3h) for cycle in mapping}
    if any(value is None or value < 0 for value in thresholds.values()):
        raise ValueError('each cycle needs a nonnegative flow threshold')

    day = datetime.strptime(daystamp, '%Y-%m-%d')
    end = day + timedelta(days=1)
    start = day - timedelta(seconds=target_window_seconds + plateau_duration_seconds + max_gap_seconds)
    observations = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            observed = datetime.strptime(entry.get('timestamp'), STAMP_FORMAT)
        except (TypeError, ValueError):
            continue
        if start <= observed < end:
            # Malformed states remain an explicit missing-data observation.
            observations[observed] = entry.get('states') if isinstance(entry.get('states'), dict) else {}

    windows = {cycle: deque() for cycle in mapping}
    plateaus = deque()
    result = []
    for observed, states in sorted(observations.items()):
        readings, active, unknown, inconsistent = {}, [], [], []
        for cycle, meter in mapping.items():
            reading = states.get(str(meter), states.get(meter))
            reading = reading if isinstance(reading, dict) else {}
            flow = _number(reading.get('volume_flow_m3h'))
            flow = flow if flow is not None and flow >= 0 else None
            supply = _temperature(reading.get('flow_temperature_c'))
            returned = _temperature(reading.get('return_temperature_c'))
            readings[cycle] = (flow, supply, returned)
            if flow is None:
                unknown.append(cycle)
            elif flow > thresholds[cycle]:
                active.append(cycle)
                if returned is None:
                    unknown.append(cycle)
                reported_kw = _number(reading.get('power_w'))
                if reported_kw is not None and reported_kw >= 0 and supply is not None and returned is not None:
                    delivered_kw = WATER_KW_PER_M3H_K * flow * (supply - returned)
                    tolerance = max(power_tolerance_kw, power_tolerance_fraction * abs(delivered_kw))
                    if delivered_kw > power_tolerance_kw and abs(delivered_kw - reported_kw / 1000) > tolerance:
                        inconsistent.append(cycle)
                        unknown.append(cycle)

            window = windows[cycle]
            eligible = (cycle in active and cycle not in inconsistent and supply is not None and returned is not None
                        and supply >= min_plateau_temperature_c
                        and supply - returned >= min_plateau_delta_c)
            if (not eligible or (window and
                    (observed - window[-1][0]).total_seconds() > max_gap_seconds)):
                window.clear()
            if not eligible:
                continue
            window.append((observed, supply))
            # Keep the shortest trailing window spanning the required duration.
            while len(window) > 1 and (observed - window[1][0]).total_seconds() >= plateau_duration_seconds:
                window.popleft()
            if len(window) >= 4 and (observed - window[0][0]).total_seconds() >= plateau_duration_seconds:
                temperatures = [value for _, value in window]
                if max(temperatures) - min(temperatures) <= plateau_tolerance_c:
                    plateaus.append((observed, median(temperatures)))

        while plateaus and (observed - plateaus[0][0]).total_seconds() > target_window_seconds:
            plateaus.popleft()
        target, source, age = target_temperature_c, 'configured', None
        if target is None:
            source = 'unavailable'
            if plateaus:
                target = _quantile([value for _, value in plateaus], plateau_quantile)
                source = 'plateau'
                supporting = [time for time, value in plateaus if value >= target - plateau_tolerance_c]
                age = int((observed - max(supporting)).total_seconds())

        if observed < day:
            continue
        cycle_demands = {}
        for cycle, (flow, supply, returned) in readings.items():
            if flow is None or cycle in inconsistent:
                cycle_demands[cycle] = None
            elif flow <= thresholds[cycle]:
                cycle_demands[cycle] = 0.0
            elif returned is None or target is None:
                cycle_demands[cycle] = None
            else:
                cycle_demands[cycle] = WATER_KW_PER_M3H_K * flow * (target - returned)
        if inconsistent:
            demand, status = None, 'inconsistent_data'
        elif unknown:
            demand, status = None, 'missing_data'
        elif not active:
            demand, status = 0.0, 'inactive'
        elif target is None:
            demand, status = None, 'waiting_for_plateau'
        else:
            demand, status = max(0.0, sum(cycle_demands.values())), 'estimated'
        result.append({
            'timestamp': observed.strftime(STAMP_FORMAT),
            'demand_kw': round(demand, 6) if demand is not None else None,
            'cycle_demand_kw': {cycle: round(value, 6) if value is not None else None
                                for cycle, value in cycle_demands.items()},
            'target_temperature_c': round(target, 3) if target is not None else None,
            'target_source': source,
            'target_age_seconds': age,
            'target_plateau_count': len(plateaus),
            'active_cycles': active,
            'unknown_cycles': unknown,
            'inconsistent_cycles': inconsistent,
            'status': status,
        })
    return result
