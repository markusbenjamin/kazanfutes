"""
Heating control with the existing schedule, interpolation and pump voting logic.
PID history is bounded and advances only after confirmed thermostat commands.
"""

from utils.project import *
from utils.set_temperature import (interpolate_set_temperature,
                                   schedule_with_recent_history)
from utils.boiler_temperature_diagnostic import read_boiler_error
from utils.heating_rain_interlock import HeatingRainInterlock

#region PID calculation
PID_STATE_VERSION = 2
PID_MAX_GAP_SECONDS = 300.0  # A minute-based loop must not integrate an outage.
PID_MAX_LAG = 5.0
PID_MAX_BRAKING = 0.2
# Preserve the two existing thresholds; a vote threshold is not a bias limit.
PID_OVERSHOOT_VOTE_THRESHOLD = 0.2
PID_OVERSHOOT_DEADBAND = 0.5


def read_pid_gains(config):
    gains = {key: float(config[key]) for key in
             ('gain_P_lag', 'gain_I', 'gain_P_overshoot', 'gain_D')}
    if any(not math.isfinite(value) or value < 0 for value in gains.values()):
        raise ValueError('PID gains must be finite and non-negative')
    return gains


def calculate_pid_overlay(set_temp, measured_temp, sensor_timestamp,
                          valve_percent, valve_threshold, previous, gains, now, *, heating_available=True):
    """Calculate one TRV's existing PI/PD overlay without I/O.

    Integral state is a non-negative heating bias, limited to 5 K. Negative
    error unwinds it to zero instead of accumulating a future heating deficit.
    The caller must save next_state only after the TRV command is confirmed.
    Legacy state is deliberately discarded, not merely clipped to the limit.
    """
    if any(not math.isfinite(float(value)) for value in
           (set_temp, measured_temp, valve_percent, valve_threshold)):
        raise ValueError('PID inputs must be finite')
    gains = read_pid_gains(gains)
    fmt = settings['timestamp_format']
    # Timestamp trouble must not stop the room/pump control loop. With a valid
    # temperature, retain proportional control and reset uncertain I/D history.
    try:
        sample_time = datetime.strptime(sensor_timestamp, fmt)
        sample_invalid = sample_time > now
    except (TypeError, ValueError):
        sample_invalid = True
    if sample_invalid:
        sample_time = now
    signature = [gains[key] for key in
                 ('gain_P_lag', 'gain_I', 'gain_P_overshoot', 'gain_D')]
    reset_reason = None
    dt_PID = 0.0
    bias_I_prev = 0.0
    temp_prev = measured_temp
    previous_sample_time = sample_time

    if sample_invalid:
        reset_reason = 'invalid_sensor_timestamp'
    elif not isinstance(previous, dict) or previous.get('version') != PID_STATE_VERSION:
        reset_reason = 'new_or_legacy_state'
    else:
        try:
            elapsed = (now - datetime.strptime(previous['timestamp'], fmt)).total_seconds()
            integral = float(previous['bias_I'])
            previous_temp = float(previous['temp'])
            previous_target = float(previous['set_temp'])
            old_sample = datetime.strptime(previous['sensor_timestamp'], fmt)
            if (not all(math.isfinite(v) for v in (integral, previous_temp, previous_target))
                    or not 0 <= integral <= PID_MAX_LAG):
                reset_reason = 'invalid_state'
            elif previous.get('gains') != signature:
                reset_reason = 'gains_changed'
            elif elapsed < 0 or elapsed > PID_MAX_GAP_SECONDS:
                reset_reason = 'clock_change_or_gap'
            elif sample_time < old_sample:
                reset_reason = 'sensor_clock_change'
            elif set_temp < previous_target:
                reset_reason = 'target_reduced'
            else:
                dt_PID = elapsed
                bias_I_prev = integral
                temp_prev = previous_temp
                previous_sample_time = old_sample
        except (KeyError, TypeError, ValueError, OverflowError):
            reset_reason = 'invalid_state'

    error_raw = set_temp - measured_temp
    if heating_available and isinstance(previous, dict) and previous.get('heating_available') is False:
        # Never integrate a forced heating outage or apply a derivative kick on return.
        dt_PID, temp_prev, previous_sample_time = 0.0, measured_temp, sample_time
        reset_reason = 'heat_restored'
    error_pos = max(0.0, error_raw)
    bias_P_lag = gains['gain_P_lag'] * error_pos
    bias_I = bias_I_prev
    if gains['gain_I'] == 0:
        bias_I = 0.0
    elif error_raw > 0 and heating_available:
        # Limit the increment itself, not only the final output. If P already
        # saturates the output, retain I without accumulating more of it.
        headroom = max(0.0, PID_MAX_LAG - bias_P_lag - bias_I_prev)
        bias_I += min(gains['gain_I'] * error_raw * dt_PID, headroom)
    elif error_raw <= 0:
        bias_I = max(0.0, bias_I_prev + gains['gain_I'] * error_raw * dt_PID)
    bias_I = min(PID_MAX_LAG, max(0.0, bias_I))
    weight_lag = logistic_sigmoid(error_pos, 0.25, 20, 0, 1) if error_raw > 0 else 0.0
    bias_lag = weight_lag * min(PID_MAX_LAG, max(0.0, bias_P_lag + bias_I))

    # Use the measurement interval, not the control-loop interval. An unchanged
    # sample contributes no derivative; a missing history contributes no kick.
    dT = measured_temp - temp_prev
    sample_dt = (sample_time - previous_sample_time).total_seconds()
    heat_rate = dT / sample_dt if heating_available and sample_dt > 0 and reset_reason is None else 0.0
    valve_active = valve_percent > valve_threshold
    overshoot = max(0.0, measured_temp - (set_temp + PID_OVERSHOOT_DEADBAND))
    weight_overshoot = int(error_raw < -PID_OVERSHOOT_VOTE_THRESHOLD and valve_active)
    bias_P_overshoot = -gains['gain_P_overshoot'] * overshoot
    bias_D = -gains['gain_D'] * max(0.0, heat_rate)
    bias_overshoot = weight_overshoot * max(-PID_MAX_BRAKING,
                                           min(0.0, bias_P_overshoot + bias_D))
    net_bias = bias_lag + bias_overshoot
    set_PID = set_temp + net_bias
    regime = 'lag' if weight_lag > 0 else 'overshoot' if weight_overshoot else 'neutral'
    next_state = {
        'version': PID_STATE_VERSION, 'bias_I': bias_I, 'temp': measured_temp,
        'timestamp': now.strftime(fmt),
        'sensor_timestamp': None if sample_invalid else sensor_timestamp,
        'set_temp': set_temp, 'gains': signature, 'heating_available': heating_available,
    }
    return {
        'next_state': next_state, 'setpoint': set_PID,
        # Veto circulation even at the demand hysteresis boundary.
        'room_overshoot': error_raw < -PID_OVERSHOOT_VOTE_THRESHOLD,
        'log': {
            'config': dict(gains, bias_max_lag=PID_MAX_LAG,
                           bias_max_overshoot=PID_MAX_BRAKING,
                           overshoot_vote_threshold=PID_OVERSHOOT_VOTE_THRESHOLD,
                           overshoot_bias_hysteresis=PID_OVERSHOOT_DEADBAND,
                           valve_active_threshold=valve_threshold,
                           max_gap_seconds=PID_MAX_GAP_SECONDS),
            'state': {'bias_I_prev': bias_I_prev, 'bias_I': bias_I,
                      'temp_prev': temp_prev, 'temp': measured_temp,
                      'dt_PID': dt_PID, 'sample_dt': sample_dt,
                      'reset_reason': reset_reason},
            'signals': {'error_raw': error_raw, 'error_pos': error_pos,
                        'overshoot': overshoot, 'dT': dT, 'heat_rate': heat_rate,
                        'valve_active': valve_active},
            'outputs': {'bias_lag': bias_lag, 'weight_lag': weight_lag,
                        'bias_overshoot': bias_overshoot,
                        'weight_overshoot': weight_overshoot, 'net_bias': net_bias,
                        'set_temp_nominal': set_temp, 'set_temp_requested': set_PID},
            'regime': regime,
        },
    }


def apply_pid_overlay(thermostat, result, measured_temp, PID_state):
    """Confirm a write before advancing state; isolate individual TRV failures."""
    confirmed = False
    try:
        confirmed = bool(set_thermostat_state_by_id(
            thermostat, heatsetpoint=result['setpoint'],
            externalsensortemp=measured_temp))
        if not confirmed:
            ServiceException(f'TRV {thermostat} PID command was not confirmed', severity=2)
    except Exception as error:
        ServiceException(f'TRV {thermostat} PID command failed: {error}', severity=2)
    result['log']['command_confirmed'] = confirmed
    result['log']['outputs']['set_temp_effective'] = result['setpoint'] if confirmed else None
    if confirmed:
        PID_state[thermostat] = result['next_state']
    else:
        # A retry starts clean, rather than integrating time against an
        # unconfirmed command. Other rooms can still be controlled this cycle.
        PID_state.pop(thermostat, None)
    return confirmed
#endregion

def usable_control_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def complete_sensor_state(state, room_ids):
    """Keep unavailable inputs explicit; schedules and switches remain required."""
    for field in ('measured_temps', 'measured_humidity', 'sensor_last_updated',
                  'humidity_last_updated', 'occupancy', 'valve_states', 'room_states'):
        if not isinstance(state.get(field), dict):
            state[field] = {}
        for room in room_ids:
            state[field].setdefault(room, None)
    if not isinstance(state.get('pump_states'), dict):
        state['pump_states'] = {}
    for cycle in ('1', '2', '3', '4'):
        state['pump_states'].setdefault(cycle, None)
    state.setdefault('boiler_state', None)
    return state


def binary_room_vote(room, cycle, set_temp, heating_switch):
    """Base vote and override precedence, without reading any sensor inputs."""
    if set_temp == -1:
        return 0, 'c_s_m_off', False
    cycle_switch = heating_switch['cycles'][cycle]
    if cycle_switch != 0:
        return int(cycle_switch == 1), 'c_m_on' if cycle_switch == 1 else 'c_m_off', False
    room_switch = heating_switch['rooms'][room]
    if room_switch != 0:
        return int(room_switch == 1), 'r_m_on' if room_switch == 1 else 'r_m_off', False
    vote = int(set_temp == 1) if set_temp in (0, 1) else int(
        set_temp > float(heating_config[f'room_{room}_threshold_temp']))
    return vote, 't_on' if vote else 't_off', set_temp not in (0, 1)


class HeatingStatusPublisher:
    """Collect status locally; upload once after the physical control work."""
    def __init__(self):
        self.pending = {}

    def write(self, data, write_subpath):
        # A multi-location PATCH preserves other publishers' state fields and
        # replaces each supplied child map just as the old per-node PATCH did.
        self.pending.update({f'{write_subpath}/{key}': value
                             for key, value in data.items()})

    def publish(self):
        if not self.pending:
            return True
        success = False
        response = None
        detail = None
        try:
            response = requests.patch(
                settings['firebase_url'].rstrip('/') + '/system.json',
                json=self.pending, timeout=3,
            )
            response.raise_for_status()
            success = True
        except Exception as error:
            detail = (f'HTTP {response.status_code}: {response.text[:300]}'
                      if response is not None else str(error))
            report(f'Firebase status upload failed; local control completed: {detail}')
            ServiceException('Firebase status upload failed; local control completed',
                             original_exception=error, severity=1)
        log({'success_firebase_publish': success, 'firebase_error': detail})
        return success


if True:
    settings["log"] = True
    settings["verbosity"] = False

#region Initialize
report('\nINITIALIZE')
success = False
system_node = HeatingStatusPublisher()
try:
    rooms = get_rooms_info()
    cycles = get_cycles_info()
    heating_config = load_json_to_dict('config/heating_control_config.json')
    condensed_schedule = load_json_to_dict('config/scheduling/condensed_schedule.json')
    system_node.write({'last_updated':timestamp(),'error':False,'where':None},'control/error')
    report('Successfully loaded config files.')

    COMMANDS_PATH = os.path.join(get_project_root(), "data", "heating_control", "commands.json")
    COMMANDS_ARCHIVE_PATH = os.path.join(get_project_root(), "data", "heating_control", "commands_archive.json")

    success = True
except ModuleException as e:
    system_node.write({'last_updated':timestamp(),'error':True,'where':'init'},'control/error')
    ServiceException(f"Module error while trying to initialize heating control", original_exception=e, severity = 3)
except Exception:
    system_node.write({'last_updated':timestamp(),'error':True,'where':'init'},'control/error')
    ServiceException(f"Unexpected error while trying to initialize heating control", severity = 3)

log({f"success_initialize":success})

#region Update heating switch
report('\nCHECK HEATING SWITCH')
def acquire_heating_switch():
    """
    Returns the heating system switch state.
    Does not exit; main decides what to run.
    """
    try:
        heating_switch = load_json_to_dict('config/heating_switch.json')
        return heating_switch

    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'switch'},'control/error')
        ServiceException("Couldn't load system switch")
#endregion

#region Get and export system state
"""
    Measure actual temps.
    Get thermostat temps.
    Get occupancy states.
    Extract set temps from schedule.
    Get valve states.
    Get boiler and pump states.
    Log to service log.
    Save to system_state.json.
    Upload to Firebase.
"""

def get_system_state():
    report('\nACQUIRING SYSTEM STATE')
    system_state = complete_sensor_state({}, rooms)

    success = False
    try:
        report("Acquiring measured temps and humidity.",verbose=True)
        room_temps_and_humidity = get_room_temps_and_humidity(just_controlled=False)

        measured_temps = system_state['measured_temps']
        measured_humidity = system_state['measured_humidity']
        sensor_last_updated = system_state['sensor_last_updated']
        humidity_last_updated = system_state['humidity_last_updated']

        for room, vals in room_temps_and_humidity.items():
            #print(f"{room}, {vals['temp']}, {vals['hum']}, {vals['last_updated']}, {vals['thermostat_temp']}, {vals['thermostat_last_updated']}")

            if not isinstance(vals, dict):
                continue
            if usable_control_number(vals.get('temp')):
                measured_temps[room] = vals['temp'] / 100
                sensor_last_updated[room] = vals.get('last_updated')
            elif usable_control_number(vals.get('thermostat_temp')):
                measured_temps[room] = vals['thermostat_temp']
                sensor_last_updated[room] = vals.get('thermostat_last_updated')
            else:
                measured_temps[room] = None
                sensor_last_updated[room] = None

            if usable_control_number(vals.get('hum')):
                measured_humidity[room] = vals['hum'] / 100
                humidity_last_updated[room] = vals.get('humidity_last_updated') or vals.get('last_updated')
            else:
                measured_humidity[room] = None
                humidity_last_updated[room] = None

        system_state['measured_temps'] = measured_temps
        system_state['measured_humidity'] = measured_humidity
        system_state['sensor_last_updated'] = sensor_last_updated
        system_state['humidity_last_updated'] = humidity_last_updated

        report("Successfully acquired measured temps and humidity.")
        success = True

    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'temps'},'control/error')
        ServiceException(f"Module error while acquiring measured temps and humidity", original_exception=e, severity = 3)

    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'temps'},'control/error')
        ServiceException(f"Unexpected error while acquiring measured temps and humidity", severity = 3)

    log({f"success_acquire_measured_temps_and_humidity":success})

    success = False
    try:
        report("Acquiring occupancy.",verbose=True)
        occupancy = get_rooms_occupancy()

        system_state['occupancy'] = occupancy

        report("Successfully acquired occupancy states.")
        success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'occupancy'},'control/error')
        ServiceException(f"Module error while acquiring occupancy states", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'occupancy'},'control/error')
        ServiceException(f"Unexpected error while acquiring occupancy states", severity = 3)

    log({f"success_acquire_occupancy_states":success})

    success = False
    try:
        report("Acquiring set temps.",verbose=True)
        current_timepoint_info = generate_timepoint_info()
        unix_day = current_timepoint_info['unix_day']
        hour_of_day = current_timepoint_info['hour_of_day']
        max_lookahead_hours = 24  # DEV: move to config
        interp_window_hours = 3   # DEV: move to config

        set_temps = {}
        set_temps_interp = {}
        # The scheduler starts at today; retain only enough past context for
        # a ramp spanning midnight, without changing schedule generation.
        try:
            previous_history = load_json_to_dict('system/state.json').get('set_temp_schedule_history', {})
        except ModuleException:
            previous_history = {}
        schedule_history = {}

        # fractional position within the current hour for interpolation
        now = datetime.now()
        hour_fraction = now.minute / 60.0 + now.second / 3600.0

        for room, schedule_for_days in condensed_schedule.items():
            schedule_for_days, schedule_history[room] = schedule_with_recent_history(
                schedule_for_days, previous_history.get(room, {}), unix_day, hour_of_day)
            # current nominal set
            set_now = schedule_for_days[str(unix_day)][str(hour_of_day)]
            set_temps[room] = set_now

            set_temps_interp[room] = interpolate_set_temperature(
                schedule_for_days, unix_day, hour_of_day, hour_fraction,
                interp_window_hours, max_lookahead_hours)

        system_state['set_temps'] = set_temps
        system_state['set_temps_interp'] = set_temps_interp
        system_state['set_temp_schedule_history'] = schedule_history

        report("Successfully acquired set temps and interpolated temps.")
        success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'set'},'control/error')
        ServiceException(f"Module error while acquiring set temps", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'set'},'control/error')
        ServiceException(f"Unexpected error while acquiring set temps", severity = 3)

    log({f"success_acquire_set_temps":success})

    success = False
    try:
        report("Acquiring valve states.",verbose=True)
        valve_states = system_state['valve_states']
        valve_reads_succeeded = True
        for room, info in rooms.items():
            valve_states_for_room = []
            if isinstance(info["thermostats"], str):
                for th in (t.strip() for t in info["thermostats"].split(";") if t.strip()):
                    try:
                        valve_states_for_room.append(get_thermostat_state_by_id(th,["valve"])["valve"])
                    except Exception as error:
                        valve_states_for_room.append(None)
                        valve_reads_succeeded = False
                        ServiceException(f"Could not read valve {th} for room {room}", original_exception=error, severity=2)
            else:
                if info['thermostats']:
                    valve_states_for_room.append(100)
                else:
                    valve_states_for_room.append(0)

            valve_states[room] = valve_states_for_room

        system_state['valve_states'] = valve_states
        report("Acquired valve states; unavailable readings remain unknown.")
        success = valve_reads_succeeded
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'valve'},'control/error')
        ServiceException(f"Module error while acquiring valve states", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'valve'},'control/error')
        ServiceException(f"Unexpected error while acquiring valve states", severity = 3)
    log({f"success_acquire_valve_states":success})

    success = False
    try:
        report("Acquiring room states.",verbose=True)
        prev_system_state = load_json_to_dict("system/state.json")
        system_state['room_states'] = prev_system_state['room_states']

        report("Successfully acquired room states.")
        success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'room_states'},'control/error')
        ServiceException(f"Module error while acquiring room states", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'room_states'},'control/error')
        ServiceException(f"Unexpected error while acquiring room states", severity = 3)

    success = False
    try:
        report("Acquiring pump states.",verbose=True)
        success = True
        for cycle in system_state['pump_states']:
            try:
                system_state['pump_states'][cycle] = get_pump_state(cycle)
            except Exception as error:
                success = False
                ServiceException(f"Could not read pump {cycle}; its state is unknown", original_exception=error, severity=2)
        report("Acquired pump states; unavailable states remain unknown.")
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'pump_states'},'control/error')
        ServiceException(f"Module error while acquiring pump states", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'pump_states'},'control/error')
        ServiceException(f"Unexpected error while acquiring pump states", severity = 3)

    log({f"success_acquire_pump_states":success})

    success = False
    try:
        report("Acquiring boiler state.",verbose=True)
        system_state['boiler_state'] = get_boiler_state()

        report("Successfully acquired boiler state.")
        success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'boiler_state'},'control/error')
        ServiceException(f"Module error while acquiring boiler state", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'boiler_state'},'control/error')
        ServiceException(f"Unexpected error while acquiring boiler state", severity = 3)

    log({f"success_acquire_boiler_state":success})
    return complete_sensor_state(system_state, rooms)
#endregion

#region Compare and command
def compare_and_command(heating_switch:dict, system_state:dict):
    """Start from schedule/override votes; refine each room using usable inputs.

    Unknown temperatures use the room's configured binary threshold. Missing
    valve feedback uses temperature hysteresis. Room failures retain the base
    vote, while available rooms and actuators continue independently.
    """
    report('\nCOMPARING SET TEMPS TO ACTUAL TEMPS TO DETERMINE VOTES')
    success = False
    control = {}
    pump_votes = None
    boiler_vote = None
    interlock = globals().get('rain_interlock')
    try:
        if interlock is not None:
            interlock.prepare(system_state['pump_states'], heating_switch['system'] == 1)
        rooms_info = get_rooms_info()
        room_votes = {}
        cycle_votes = {'1':0,'2':0,'3':0,'4':0}
        report('Room votes:',verbose=True)
        control['rooms'] = {}
        try:
            PID_state = load_json_to_dict("system/PID_state.json")
        except ModuleException:
            report("PID state unavailable; initializing bounded state.", verbose=True)
            PID_state = {}
        if not isinstance(PID_state, dict):
            PID_state = {}
        gains = read_pid_gains(heating_config)
        active_PID_thermostats = set()
        pid_commands_confirmed = True
        PID_log = {}

        complete_sensor_state(system_state, rooms_info)
        room_failures = False

        def refine_room_vote(room, set_temp, fallback_vote, fallback_reason):
            nonlocal pid_commands_confirmed
            measured_temp = system_state['measured_temps'][room]
            sensor_last_updated = system_state['sensor_last_updated'][room]
            try:
                minutes_since_update = round((datetime.now() - datetime.strptime(
                    sensor_last_updated, settings['timestamp_format'])).total_seconds() / 60)
            except (TypeError, ValueError):
                minutes_since_update = None
            if (not usable_control_number(measured_temp) or minutes_since_update is None
                    or minutes_since_update > float(heating_config['temp_data_expiry'])):
                return fallback_vote, fallback_reason, 'temperature unavailable/expired; timed fallback'

            previous_vote = system_state['room_states'][room]
            if previous_vote not in (0, 1):
                previous_vote = fallback_vote
            thermostat_ids = rooms_info[room]['thermostats']
            thermostats = [th.strip() for th in thermostat_ids.split(';') if th.strip()] if isinstance(thermostat_ids, str) else []
            valves = system_state['valve_states'][room]
            valves_usable = (bool(thermostats) and isinstance(valves, (list, tuple))
                             and len(valves) == len(thermostats)
                             and all(usable_control_number(v) and 0 <= v <= 100 for v in valves))
            if not valves_usable:
                # Use existing temperature hysteresis when valve feedback is unavailable.
                # Do not invent a TRV demand or send a fallback TRV command.
                buffer = float(heating_config['hysteresis_buffer'])
                upper = PID_OVERSHOOT_VOTE_THRESHOLD if thermostats else buffer
                relation = f'{measured_temp} °C vs {set_temp} °C; temperature control'
                if thermostats:
                    relation += '; valve feedback unavailable'
                if measured_temp < set_temp - buffer:
                    return 1, 'below', relation
                if measured_temp > set_temp + upper:
                    return 0, 'above', relation
                return previous_vote, 'h_on' if previous_vote else 'h_off', relation

            demand_open = int(heating_config['demand_hysteresis_open_min'] if previous_vote == 0
                              else heating_config['demand_hysteresis_close'])
            demand = max(valves)
            room_overshoot = False
            bias_report = []
            for thermostat, valve in zip(thermostats, valves):
                availability = {} if interlock is None or interlock.integration_allowed(cycle) else {'heating_available': False}
                result = calculate_pid_overlay(set_temp, measured_temp, sensor_last_updated,
                                               valve, demand_open, PID_state.get(thermostat),
                                               gains, datetime.now(), **availability)
                active_PID_thermostats.add(thermostat)
                room_overshoot = room_overshoot or result['room_overshoot']
                bias_report.append(result['log']['outputs']['net_bias'])
                confirmed = apply_pid_overlay(thermostat, result, measured_temp, PID_state)
                pid_commands_confirmed = confirmed and pid_commands_confirmed
                PID_log[room][thermostat] = result['log']
            relation = f'{demand}% demand, {measured_temp} °C vs {set_temp} °C, bias: {bias_report}'
            if room_overshoot:
                return 0, 'above', relation
            if demand < demand_open:
                return 0, 'd_low', relation
            if demand > demand_open:
                return 1, 'd_high', relation
            return previous_vote, 'd_h_on' if previous_vote else 'd_h_off', relation

        for room in rooms_info:
            set_temp = max(system_state['set_temps'][room], system_state['set_temps_interp'][room])
            cycle = room_to_cycle(room)
            # Establish the sensor-independent vote before attempting any refinement.
            room_vote, reason_control, automatic = binary_room_vote(room, cycle, set_temp, heating_switch)
            relation = 'scheduled or manual on/off control'
            PID_log[room] = {}
            if automatic:
                try:
                    room_vote, reason_control, relation = refine_room_vote(room, set_temp, room_vote, reason_control)
                except Exception as error:
                    # Assignment above is atomic: on failure the base vote is retained.
                    room_failures = True
                    relation = 'room calculation failed; retaining timed fallback'
                    thermostat_ids = rooms_info[room]['thermostats']
                    if isinstance(thermostat_ids, str):
                        for thermostat in thermostat_ids.split(';'):
                            active_PID_thermostats.discard(thermostat.strip())
                    system_node.write({'last_updated':timestamp(), 'error':True,
                                       'where':f'room_{room}'}, 'control/error')
                    ServiceException(f'Room {room} control failed; using its schedule fallback',
                                     original_exception=error, severity=3)
            name = rooms_info[room]['name']
            label = '[' + name + ']' if system_state['occupancy'][room] else name
            report(f"\t{reason_control} ({relation}): {label} voting {['OFF','ON'][room_vote]} for cycle {cycle}.", verbose=True)
            control['rooms'][room] = {'vote':room_vote,'reason':reason_control}
            room_votes[room] = room_vote
            system_state['room_states'][room] = room_vote
            cycle_votes[cycle] += room_vote

        # Drop history for disabled/degraded rooms so re-enabling cannot reuse
        # an old integral or integrate the time spent outside PID control.
        PID_state = {th: state for th, state in PID_state.items()
                     if th in active_PID_thermostats}
        export_dict_as_json(PID_state, "system/PID_state.json")

        control['cycles'] = {}
        pump_votes = {}
        for cycle,votes in cycle_votes.items():
            pump_votes[cycle] = sign(votes)
            control['cycles'][cycle] = sign(votes)

        boiler_vote = sign(sum(list(pump_votes.values())))
        if interlock is not None:
            control['heat_requests'] = dict(pump_votes)
            pump_votes, boiler_vote = interlock.decide(pump_votes)
            control['cycles'] = dict(pump_votes)
            control['rain_protection'] = interlock.status
            interlock.control = control
            if interlock.prepared_policy['inhibit']:
                system_state['mode'] = 'rain_residual_heat' if any(pump_votes.values()) else 'rain_shutdown'
            else:
                system_state['mode'] = 'heating_on'
        control['boiler'] = boiler_vote

        log({'PID_state':PID_log})
        log({'room_votes':room_votes})
        log({'cycle_votes':cycle_votes})
        log({'pump_votes':pump_votes})
        log({'boiler_vote':boiler_vote})

        cycles_info = get_cycles_info()
        report(f"Cycle votes:\n\t" +
            '\n\t'.join([
                cycles_info[cycle]['name'] + ': ' + str(vote) + ' room wants heating.'
                for
                cycle, vote
                in cycle_votes.items()
            ]), verbose=True)
        report(f"Pump votes: " +
            ', '.join([
                f"{pump}: {['OFF', 'ON'][vote]}"
                for pump, vote
                in pump_votes.items()
            ]) + ".", verbose=True)
        report(f"Pump states: " +
            ', '.join([
                f"{pump}: {'ON' if state == 1 else 'OFF' if state == 0 else 'UNKNOWN'}"
                for pump, state
                in system_state['pump_states'].items()
            ]) + ".", verbose=True)
        report(f"Boiler vote: {['OFF','ON'][boiler_vote]}",verbose=True)
        report(f"Boiler state: {system_state['boiler_state']} (None means unknown)",verbose=True)

        control['pid_commands_confirmed'] = pid_commands_confirmed
        control['last_updated'] = timestamp()
        system_node.write(control,'control')
        export_dict_as_json(control,'system/control.json')
        success = pid_commands_confirmed and not room_failures
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'voting'},'control/error')
        ServiceException(f"Module error while voting", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'voting'},'control/error')
        ServiceException(f"Unexpected error while voting", severity = 3)

    log({f"success_voting":success})

    if pump_votes is None or boiler_vote is None:
        log({'success_issuing_command': False})
        return

    report('\nISSUING COMMANDS')
    def issue_command(existing_commands, device:str, delay:float, setting:int):
        due_time = datetime.now() + timedelta(minutes=delay)
        command = {
                    'issuance_timestamp':timestamp(),
                    'due_timestamp':timestamp(due_time),
                    'device':device,
                    'setting':setting,
                    'executed':False,
                    'execution_timestamp':None
                }
        if device == 'boiler' and setting == 1 and interlock is not None:
            command['heat_generation'] = interlock.prepared_policy.get('generation')

        redundant = False
        for existing_command in existing_commands:
            if not existing_command['executed'] and existing_command['device'] == device: # Only inspect unexecuted commands and for the same device
                if timestamp_to_datetime(existing_command['due_timestamp']) < due_time:
                    redundant = True
        if not redundant:
            log({'command_issuance':{'device':device,'state':setting}})
            report(f"Issuing command to turn '{device}' {['OFF','ON'][setting]} in {delay} minutes.",verbose=True)
            return command
        else:
            report(f"Command ('{device}': {['OFF','ON'][setting]}) already issued.",verbose=True)

    success = False
    try:
        existing_commands = load_commands(COMMANDS_PATH)
        desired = {f'pump_{cycle}': vote for cycle, vote in pump_votes.items()}
        desired['boiler'] = boiler_vote
        # A failed command must not survive a later opposite decision.
        existing_commands = [command for command in existing_commands
                             if command['executed'] or command['device'] not in desired
                             or command['setting'] == desired[command['device']]]
        new_commands = []
        cycles_info = get_cycles_info()
        append_valid_command = (lambda command: new_commands.append(command) if command else None)
        for cycle, info in cycles_info.items():
            if system_state['pump_states'][cycle] != pump_votes[cycle]:
                delay = [0, 0][pump_votes[cycle]] # In theory 3 mins cooloff when turning off a cycle would be nice, skipping now so there won't be forgotten commands
                append_valid_command(issue_command(existing_commands, f'pump_{cycle}', delay, pump_votes[cycle]))
        if system_state['boiler_state'] != boiler_vote:
            append_valid_command(issue_command(existing_commands,'boiler',0,boiler_vote))

        refresh_commands(existing_commands + new_commands)
        success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'issue_commands'},'control/error')
        ServiceException(f"Module error while issuing commands", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'issue_commands'},'control/error')
        ServiceException(f"Unexpected error while issuing commands", severity = 3)

    log({f"success_issuing_command":success})

def push_commands(commands_path:str,commands:list,append = False):
    try:
        if not os.path.exists(commands_path):
            with open(commands_path, 'w') as commands_file:
                json.dump([], commands_file)
        existing_commands = []
        if append:
            existing_commands = load_commands(commands_path)
        with open(commands_path, 'w') as commands_file:
            json.dump(existing_commands + commands, commands_file, indent=4)
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'push_commands'},'control/error')
        ServiceException(f"Module error while writing commands to {commands_path}", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'push_commands'},'control/error')
        ServiceException(f"Unexpected error while writing commands to {commands_path}", severity = 3)

def refresh_commands(commands):
    push_commands(COMMANDS_PATH,commands)

def archive_commands(commands):
    push_commands(COMMANDS_ARCHIVE_PATH,commands,True)

def load_commands(commands_path):
    try:
        if not os.path.exists(commands_path):
            with open(commands_path, 'w') as commands_file:
                json.dump([], commands_file)
        with open(commands_path, 'r') as commands_file:
            return json.load(commands_file)
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'load_commands'},'control/error')
        ServiceException(f"Module error while loading commands", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'load_commands'},'control/error')
        ServiceException(f"Unexpected error while loading commands", severity = 3)
#endregion

#region Execute commands
def execute_commands():
    """
    Simply load commands for pumps and the boiler then execute the latest actual.
    If successful, set executed to True and set execution timestamp.
    """
    report('\nEXECUTING COMMANDS')
    success = False
    interlock = globals().get('rain_interlock')
    try:
        if interlock is not None:
            try:
                forced = interlock.ensure_boiler_off(set_boiler_state, get_boiler_state)
                if forced and forced[1]:
                    system_state['boiler_state'] = 0
            except Exception as error:
                interlock.boiler_off_confirmed = False
                ServiceException('Could not confirm rain boiler-OFF; continuing pump control',
                                 original_exception=error, severity=3)
        commands = load_commands(COMMANDS_PATH)
        if interlock is not None and interlock.policy()['inhibit']:
            commands = [c for c in commands if c['device'] != 'boiler' or c['setting'] != 1]
        executed_commands = list(filter(lambda command:command['executed'],commands))
        future_commands = list(filter(lambda command:datetime.now()<timestamp_to_datetime(command['due_timestamp']),commands))
        latest_unexecuted_commands_past_due = []
        for device in ['pump_1','pump_2','pump_3','pump_4','boiler']: # So the latest for a given device can be selected
            try:
                latest_unexecuted_command_past_due = sorted(
                    list(filter(
                    lambda command:
                    not command['executed'] and # As of yet unexecuted commands
                    command['device'] == device and # For this device
                    timestamp_to_datetime(command['due_timestamp'])<datetime.now(), # That are past due
                    commands
                    )),
                    key=lambda command: timestamp_to_datetime(command['issuance_timestamp']) # Sort by timestamp just to make sure
                )[-1] # Select latest
                latest_unexecuted_commands_past_due.append(latest_unexecuted_command_past_due) # Does not copy, just creates new reference so the list of loaded commands is still directly affected (which is good)
            except IndexError: pass

        command_successes = []
        complete_sensor_state(system_state, [])
        for command in latest_unexecuted_commands_past_due:
            try:
                if interlock is not None:
                    actual, confirmed = interlock.actuate(
                        command['device'], command['setting'], set_boiler_state,
                        get_boiler_state, set_pump_state, generation=command.get('heat_generation'))
                    if actual != command['setting']:
                        command['blocked_setting'] = command['setting']
                        command['setting'] = actual
                        command['restriction'] = 'rain_interlock'
                    if confirmed:
                        if command['device'] == 'boiler':
                            system_state['boiler_state'] = actual
                        else:
                            system_state['pump_states'][command['device'][-1]] = actual
                elif command['device'] == 'boiler':
                    confirmed = bool(set_boiler_state(command['setting']))
                    if confirmed:
                        system_state['boiler_state'] = command['setting']
                else:
                    pump = command['device'][-1]
                    confirmed = bool(set_pump_state(pump, command['setting']))
                    if confirmed:
                        system_state['pump_states'][pump] = command['setting']
                if confirmed:
                    report(f"Command executed: '{command['device']}': {['OFF','ON'][command['setting']]}.",verbose=True)
                    command['executed'] = True
                    command['execution_timestamp'] = timestamp()
                command_successes.append(confirmed)
            except Exception as error:
                command_successes.append(False)
                ServiceException(f"Command failed for {command['device']}; continuing other devices",
                                 original_exception=error, severity=3)

        newly_executed_commands = list(filter(lambda command:command['executed'],latest_unexecuted_commands_past_due))
        still_unexecuted_commands = list(filter(lambda command:not command['executed'],latest_unexecuted_commands_past_due))

        refresh_commands(future_commands + still_unexecuted_commands)
        archive_commands(executed_commands + newly_executed_commands)

        success = all(command_successes)
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'execute_commands'},'control/error')
        ServiceException(f"Module error while executing commands", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'execute_commands'},'control/error')
        ServiceException(f"Unexpected error while executing commands", severity = 3)
    finally:
        if interlock is not None:
            try:
                forced = interlock.ensure_boiler_off(set_boiler_state, get_boiler_state)
                if forced and forced[1]:
                    system_state['boiler_state'] = 0
            except Exception as error:
                interlock.boiler_off_confirmed = False
                ServiceException('Could not confirm rain boiler-OFF', original_exception=error, severity=3)
            # Safety OFF decisions must survive an unreadable/failed command queue.
            # Each pump remains isolated: a failure cannot stop the next circuit.
            if interlock.policy()['inhibit']:
                for cycle, decision in interlock.status.get('cycles', {}).items():
                    if decision['pump_command'] != 0 or system_state['pump_states'].get(cycle) == 0:
                        continue
                    try:
                        actual, confirmed = interlock.actuate(
                            'pump_' + cycle, 0, set_boiler_state, get_boiler_state, set_pump_state)
                        if confirmed:
                            system_state['pump_states'][cycle] = actual
                        else:
                            raise RuntimeError('Pump OFF was not confirmed')
                    except Exception as error:
                        ServiceException(f'Rain pump-OFF failed for circuit {cycle}', original_exception=error, severity=3)
            try:
                interlock.publish_ack(system_state)
                control = getattr(interlock, 'control', None)
                if control is not None:
                    control['cycles'] = {c: v['pump_command'] for c, v in interlock.status['cycles'].items()}
                    if interlock.effective_boiler_command is not None:
                        control['boiler'] = interlock.effective_boiler_command
                    control['last_updated'] = timestamp()
                    export_dict_as_json(control, 'system/control.json')
                    system_node.write(control, 'control')
                if interlock.status['boiler_inhibited']:
                    system_state['mode'] = ('rain_residual_heat' if any(
                        v['pump_command'] for v in interlock.status.get('cycles', {}).values()) else 'rain_shutdown')
            except Exception as error:
                ServiceException('Rain heating acknowledgement failed', original_exception=error, severity=3)

    log({'success_executing_commands':success})

#endregion

#region Export final state

def export_system_state():
    success = False
    # Reporting only, after actuation. Always clear an earlier diagnostic first.
    system_state['boiler_error'] = ''
    try:
        interlock = globals().get('rain_interlock')
        if interlock is None or interlock.generation_expected():
            system_state['boiler_error'] = read_boiler_error(get_project_root(), heating_switch, datetime.now())
    except Exception as error:
        # A diagnostic failure must not alter control/error or prevent publication.
        report(f"Boiler temperature diagnostic unavailable: {error}", verbose=True)
    try:
        log(system_state)
        system_state['last_updated'] = timestamp()
        system_node.write(system_state,'state')
        export_dict_as_json(system_state,'system/state.json')
        success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'system_state_export'},'control/error')
        ServiceException(f"Module error while exporting system state", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'system_state_export'},'control/error')
        ServiceException(f"Unexpected error while exporting system state", severity = 3)

    log({f"success_export_system_state":success})

#endregion

if __name__ == '__main__':
    #settings['dev'] = True
    if settings['dev']:
        settings['log'] = False

    settings['verbosity'] = True

    rain_interlock = HeatingRainInterlock(get_project_root())
    if rain_interlock.enabled:
        rain_interlock.acquire_loop()
    else:
        rain_interlock = None

    heating_switch = acquire_heating_switch()
    system_state = get_system_state()

    if heating_switch['system'] == 0:
        report('Heating is switched off in config file.')

        system_state['mode'] = 'heating_off'

        if settings['on_raspi']:
            try:
                stopped = shutdown_heating()
                if rain_interlock is not None:
                    rain_interlock.prepare(system_state['pump_states'], master_on=False)
                    rain_interlock.decide({c: 0 for c in ('1', '2', '3', '4')})
                    actual, confirmed = rain_interlock.actuate(
                        'boiler', 0, set_boiler_state, get_boiler_state, set_pump_state)
                    if confirmed:
                        system_state['boiler_state'] = 0
                    if stopped:
                        system_state['pump_states'] = {c: 0 for c in ('1', '2', '3', '4')}
                    rain_interlock.publish_ack(system_state)
                export_dict_as_json({}, "system/PID_state.json")
            except ModuleException as e:
                system_node.write({'last_updated':timestamp(),'error':True,'where':'shutdown_heating'},'control/error')
                ServiceException(f"Module error while shutting down heating", original_exception=e, severity = 3)
            except Exception:
                system_node.write({'last_updated':timestamp(),'error':True,'where':'shutdown_heating'},'control/error')
                ServiceException(f"Unexpected error while shutting down heating", severity = 3)

        export_system_state()
        system_node.publish()
        exit()

    compare_and_command(heating_switch, system_state)
    execute_commands()
    export_system_state()
    system_node.publish()
