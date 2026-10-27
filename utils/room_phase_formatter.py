"""Causal room error / emitter-temperature trajectories; never controls devices.

Room-level models deliberately do not infer individual TRV/probe associations.
All parameters, input ages and measurement/model provenance are explicit.
"""
from bisect import bisect_right
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from statistics import mean, median
import json
import math

STAMP = '%Y-%m-%d-%H-%M-%S'
DEFAULT_MODEL = {'heat_tau_s': 600., 'cool_tau_s': 1200., 'gain': 1., 'valve_exponent': .7}
HEATING_MODELS = [dict(heat_tau_s=tau, gain=gain, valve_exponent=power)
                  for tau, gain, power in product((180., 600., 1200.), (.6, .8, 1.), (.35, .7, 1.))]
COOLING_TAUS = (300., 900., 1800., 3600.)


def _number(value):
    return float(value) if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) else None


def _stamp(value):
    try:
        return datetime.strptime(value, STAMP)
    except (TypeError, ValueError):
        return None


class _History:
    def __init__(self, rows, field):
        values = {}
        for row in rows:
            observed = _stamp(row.get('timestamp'))
            if observed is not None and isinstance(row.get(field), dict):
                values[observed] = row[field]
        self.times = sorted(values)
        self.values = [values[time] for time in self.times]

    def at(self, time, max_age):
        index = bisect_right(self.times, time) - 1
        if index < 0 or (time - self.times[index]).total_seconds() > max_age:
            return None
        return self.values[index]


def _equilibrium(room_temp, water_temp, opening, pump, model):
    if room_temp is None or pump not in (0, 1):
        return None
    if pump == 0 or opening == 0:
        return room_temp
    if opening is None or water_temp is None:
        return None
    return room_temp + model['gain'] * opening ** model['valve_exponent'] * max(water_temp - room_temp, 0.)


def _step(previous, equilibrium, seconds, tau):
    return equilibrium + (previous - equilibrium) * math.exp(-seconds / tau)


class _Fit:
    """Small causal candidate fit; no fitting on future samples in the day."""
    def __init__(self):
        self.heat_errors = [0.] * len(HEATING_MODELS)
        self.cool_errors = [0.] * len(COOLING_TAUS)
        self.heat_count = self.cool_count = 0
        self.heat_movement = self.cool_movement = 0.
        self.previous = None

    def observe(self, time, measured, room_temp, water, opening, pump):
        previous = self.previous
        self.previous = (time, measured, pump, opening)
        if previous is None or measured is None or previous[1] is None or room_temp is None:
            return
        seconds = (time - previous[0]).total_seconds()
        if not 0 < seconds <= 180:
            return
        if pump != previous[2] or (pump == 1 and
                (opening is None or previous[3] is None or abs(opening - previous[3]) > .05)):
            return
        # Fit heating only well inside a flowing/open state. Off samples fit cooling.
        if pump == 1 and opening is not None and opening > .05 and water is not None and water > room_temp + 5:
            for index, candidate in enumerate(HEATING_MODELS):
                equilibrium = _equilibrium(room_temp, water, opening, pump, candidate)
                predicted = _step(previous[1], equilibrium, seconds, candidate['heat_tau_s'])
                self.heat_errors[index] += min((predicted - measured) ** 2, 100.)
            self.heat_count += 1
            self.heat_movement += abs(measured - previous[1])
        elif pump == 0 or opening == 0:
            for index, tau in enumerate(COOLING_TAUS):
                predicted = _step(previous[1], room_temp, seconds, tau)
                self.cool_errors[index] += min((predicted - measured) ** 2, 100.)
            self.cool_count += 1
            self.cool_movement += abs(measured - previous[1])

    def parameters(self):
        model = dict(DEFAULT_MODEL)
        fitted = []
        # Enough observations and actual thermal movement, not just many flat samples.
        if self.heat_count >= 60 and self.heat_movement >= 10:
            index = min(range(len(HEATING_MODELS)), key=self.heat_errors.__getitem__)
            if self.heat_errors[index] / self.heat_count <= 4:
                model.update(HEATING_MODELS[index])
                fitted.append('heating')
        if self.cool_count >= 30 and self.cool_movement >= 5:
            index = min(range(len(COOLING_TAUS)), key=self.cool_errors.__getitem__)
            if self.cool_errors[index] / self.cool_count <= 4:
                model['cool_tau_s'] = COOLING_TAUS[index]
                fitted.append('cooling')
        return model, fitted


def format_room_phase_points(control_entries, probe_entries, water_entries, daystamp, rooms, mapping,
                             meter_mapping, *, end_time=None, offset_k=20., sensor_max_age_s=3600,
                             probe_max_age_s=180, water_max_age_s=180, model_max_gap_s=180,
                             valve_entries=None):
    """One point per recorded control snapshot, including explicit unavailable rows.

    Previous-day inputs warm the state and causal calibration. Probe aggregation
    has fixed mapped membership: a lost cold probe cannot make a mean jump hot.
    Missing measured probes use the whole-room estimate, never a partial mean.
    The return/supply mean is used for model water temperature. No future data,
    nominal-target fallback, demand gating, or inferred device placement.
    """
    if _number(offset_k) is None or any(_number(v) is None or v <= 0 for v in
            (sensor_max_age_s, probe_max_age_s, water_max_age_s, model_max_gap_s)):
        raise ValueError('Offset must be finite; age limits must be positive')
    day = datetime.strptime(daystamp, '%Y-%m-%d')
    end = min(day + timedelta(days=1), end_time) if end_time else day + timedelta(days=1)
    controls = {}
    for row in control_entries:
        time = _stamp(row.get('timestamp'))
        if time is not None and day - timedelta(days=1) <= time < end and isinstance(row.get('measured_temps'), dict):
            controls[time] = row
    probes = _History(probe_entries, 'devices')
    water = _History(water_entries, 'states')
    valve_history = _History(valve_entries or [], 'states')
    selected = {str(room): info for room, info in rooms.items() if info.get('controlled') and info.get('cycle') is not None}
    sources = {room: sorted({(probe['device'], probe['probe'])
                            for unit in mapping.get('rooms', []) if int(room) in unit.get('legacy_room_numbers', [])
                            for probe in unit.get('probes', [])}) for room in selected}
    state = {room: {'temperature': None, 'last': None, 'warm_seconds': 0., 'fit': _Fit()} for room in selected}
    output = {room: [] for room in selected}
    summary = {room: {'measured': 0, 'estimated': 0, 'unavailable': 0} for room in selected}
    for time, row in sorted(controls.items()):
        probe_row, water_row = probes.at(time, probe_max_age_s), water.at(time, water_max_age_s)
        valve_row = valve_history.at(time, 180)
        # Pool only already-calibrated room-level models; never assume a TRV/probe pair.
        calibrated = [item['fit'].parameters() for item in state.values()]
        heating = [model for model, fitted in calibrated if 'heating' in fitted]
        cooling = [model for model, fitted in calibrated if 'cooling' in fitted]
        for room, info in selected.items():
            item, cycle = state[room], str(info['cycle'])
            seen = _stamp((row.get('sensor_last_updated') or {}).get(room))
            age = (time - seen).total_seconds() if seen else None
            temp = _number(row['measured_temps'].get(room))
            temp = temp if age is not None and -30 <= age <= sensor_max_age_s else None
            target = _number((row.get('set_temps_interp') or {}).get(room))
            # -1/0/1 encode off/timed operation, not Celsius targets.
            target = target if target is not None and 1 < target <= 50 else None
            error = target - temp if temp is not None and target is not None else None
            trvs = info.get('thermostats')
            openings = (row.get('valve_states') or {}).get(room)
            if isinstance(trvs, str) and trvs:
                count = len(trvs.split(';'))
                if valve_entries is not None:
                    values = []
                    for identifier in trvs.split(';'):
                        detail = (valve_row or {}).get(identifier, {})
                        last_seen = _stamp(detail.get('lastseen'))
                        fresh = last_seen is not None and -30 <= (time - last_seen).total_seconds() <= 3600
                        values.append(_number(detail.get('valve')) if fresh else None)
                else:
                    values = [_number(value) for value in openings] if isinstance(openings, list) else []
                opening = mean(values) / 100 if len(values) == count and all(v is not None and 0 <= v <= 100 for v in values) else None
            else:
                opening = 1.
            pump_value = (row.get('pump_states') or {}).get(cycle)
            pump = int(pump_value) if isinstance(pump_value, (int, bool)) and pump_value in (0, 1) else None
            meter = meter_mapping.get(cycle)
            reading = (water_row or {}).get(str(meter), (water_row or {}).get(meter, {}))
            supply = _number(reading.get('flow_temperature_c')) if isinstance(reading, dict) else None
            returned = _number(reading.get('return_temperature_c')) if isinstance(reading, dict) else None
            water_temp = (supply + returned) / 2 if supply is not None and returned is not None and 0 < supply < 100 and 0 < returned < 100 else None
            values = [_number((probe_row or {}).get(device, {}).get(probe)) for device, probe in sources[room]]
            measured = mean(values) if values and all(v is not None and -40 <= v <= 125 for v in values) else None
            item['fit'].observe(time, measured, temp, water_temp, opening, pump)
            model, fitted = item['fit'].parameters()
            shared = False
            if 'heating' not in fitted and heating:
                for key in ('heat_tau_s', 'gain', 'valve_exponent'):
                    model[key] = median(candidate[key] for candidate in heating)
                shared = True
            if 'cooling' not in fitted and cooling:
                model['cool_tau_s'] = median(candidate['cool_tau_s'] for candidate in cooling)
                shared = True
            quality = 'fitted' if len(fitted) == 2 else 'partly_fitted' if fitted else 'shared' if shared else 'default'
            item['model'] = {**model, 'quality': quality, 'fitted_parts': fitted}
            elapsed = (time - item['last']).total_seconds() if item['last'] else None
            equilibrium = _equilibrium(temp, water_temp, opening, pump, model)
            source, reason = 'unavailable', None
            if measured is not None:
                item['temperature'] = measured
                item['warm_seconds'] = 5 * max(model['heat_tau_s'], model['cool_tau_s'])
                source = 'measured'
            elif equilibrium is None:
                item['temperature'], item['warm_seconds'] = None, 0.
                reason = 'missing_model_input'
            else:
                if elapsed is None or elapsed > model_max_gap_s or item['temperature'] is None:
                    item['temperature'], item['warm_seconds'] = equilibrium, 0.
                else:
                    tau = model['heat_tau_s'] if equilibrium > item['temperature'] else model['cool_tau_s']
                    item['temperature'] = _step(item['temperature'], equilibrium, elapsed, tau)
                    item['warm_seconds'] += elapsed
                if item['warm_seconds'] >= 5 * max(model['heat_tau_s'], model['cool_tau_s']):
                    source = 'estimated'
                else:
                    reason = 'model_warmup'
            item['last'] = time
            effective = item['temperature'] if source != 'unavailable' else None
            intensity = max(0., effective - temp) - offset_k if effective is not None and temp is not None else None
            if error is None:
                source = 'unavailable'
                reason = 'room_temperature_stale' if temp is None else 'no_temperature_target'
            if time < day:
                continue
            point = {'timestamp': time.strftime(STAMP), 'error_k': round(error, 4) if error is not None else None,
                     'intensity_k': round(intensity, 4) if intensity is not None else None,
                     'source': source, 'reason': reason, 'model_quality': quality,
                     'room_temp_c': temp, 'set_temp_c': target,
                     'radiator_temp_c': round(effective, 4) if effective is not None else None,
                     'room_sensor_age_s': age, 'pump_on': pump,
                     'valve_fraction': round(opening, 4) if opening is not None else None}
            output[room].append(point)
            summary[room][source] += 1
    return {'schema_version': 1, 'day': daystamp, 'offset_k': offset_k,
            'limits': {'room_sensor_age_s': sensor_max_age_s, 'probe_age_s': probe_max_age_s,
                       'water_age_s': water_max_age_s, 'model_gap_s': model_max_gap_s},
            'rooms': {room: {'points': output[room], 'coverage': summary[room],
                             'model': {**state[room].get('model', DEFAULT_MODEL),
                                       'heating_samples': state[room]['fit'].heat_count,
                                       'cooling_samples': state[room]['fit'].cool_count},
                             'probe_sources': [device + '/' + probe for device, probe in sources[room]]}
                      for room in selected}}


def _read_logs(root, relative, days):
    for day, current in days:
        path = Path(root) / (relative + ('' if current else '.' + day))
        if not path.exists():
            continue
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, dict):
                    yield value


def format_room_phase_day(root, daystamp, rooms, mapping, meter_mapping, *, now=None):
    """Read only needed raw streams, with the preceding day for warm-up."""
    now = now or datetime.now()
    day = datetime.strptime(daystamp, '%Y-%m-%d')
    days = [(date.strftime('%Y-%m-%d'), date.date() == now.date())
            for date in (day - timedelta(days=1), day)]
    controls = [row for row in _read_logs(root, 'data/logs/service_execution/heating_control/heating_control.json', days)
                if isinstance(row.get('measured_temps'), dict)]
    probes = []
    for row in _read_logs(root, 'data/logs/radiator_temps/radiator_temps.json', days):
        probes.append({'timestamp': row.get('timestamp'), 'devices': {key: value for key, value in row.items() if isinstance(value, dict)}})
    water = list(_read_logs(root, 'data/logs/heat_delivery/heatmeters_state.json', days))
    valves = list(_read_logs(root, 'data/logs/thermostats/thermostats_state.json', days))
    return format_room_phase_points(controls, probes, water, daystamp, rooms, mapping, meter_mapping,
                                    end_time=now if day.date() == now.date() else None, valve_entries=valves)
