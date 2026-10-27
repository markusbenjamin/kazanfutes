"""
Heating control with the existing schedule, interpolation and pump voting logic.
PID history is bounded and advances only after confirmed thermostat commands.
"""

from utils.project import *
from utils.set_temperature import (interpolate_set_temperature,
                                   schedule_with_recent_history)

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
                          valve_percent, valve_threshold, previous, gains, now):
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
    error_pos = max(0.0, error_raw)
    bias_P_lag = gains['gain_P_lag'] * error_pos
    bias_I = bias_I_prev
    if gains['gain_I'] == 0:
        bias_I = 0.0
    elif error_raw > 0:
        # Limit the increment itself, not only the final output. If P already
        # saturates the output, retain I without accumulating more of it.
        headroom = max(0.0, PID_MAX_LAG - bias_P_lag - bias_I_prev)
        bias_I += min(gains['gain_I'] * error_raw * dt_PID, headroom)
    else:
        bias_I = max(0.0, bias_I_prev + gains['gain_I'] * error_raw * dt_PID)
    bias_I = min(PID_MAX_LAG, max(0.0, bias_I))
    weight_lag = logistic_sigmoid(error_pos, 0.25, 20, 0, 1) if error_raw > 0 else 0.0
    bias_lag = weight_lag * min(PID_MAX_LAG, max(0.0, bias_P_lag + bias_I))

    # Use the measurement interval, not the control-loop interval. An unchanged
    # sample contributes no derivative; a missing history contributes no kick.
    dT = measured_temp - temp_prev
    sample_dt = (sample_time - previous_sample_time).total_seconds()
    heat_rate = dT / sample_dt if sample_dt > 0 and reset_reason is None else 0.0
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
        'set_temp': set_temp, 'gains': signature,
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

if True:
    settings["log"] = True
    settings["verbosity"] = False

#region Initialize
report('\nINITIALIZE')
success = False
try:
    rooms = get_rooms_info()
    cycles = get_cycles_info()
    heating_config = load_json_to_dict('config/heating_control_config.json')
    condensed_schedule = load_json_to_dict('config/scheduling/condensed_schedule.json')
    system_node = JSONNodeAtURL(node_relative_path='system')
    system_node.write({'last_updated':timestamp(),'error':False,'where':None},'control/error')
    report('Successfully loaded config files and initialized Firebase connection.')

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
    system_state = {}

    success = False
    try:
        report("Acquiring measured temps and humidity.",verbose=True)
        room_temps_and_humidity = get_room_temps_and_humidity(just_controlled=False)

        measured_temps = {}
        measured_humidity = {}
        sensor_last_updated = {}
        humidity_last_updated = {}

        for room, vals in room_temps_and_humidity.items():
            #print(f"{room}, {vals['temp']}, {vals['hum']}, {vals['last_updated']}, {vals['thermostat_temp']}, {vals['thermostat_last_updated']}")

            if vals['temp'] is not None:
                measured_temps[room] = vals['temp'] / 100
                sensor_last_updated[room] = vals['last_updated']
            elif vals['thermostat_temp'] is not None:
                measured_temps[room] = vals['thermostat_temp']
                sensor_last_updated[room] = vals['thermostat_last_updated']
            else:
                measured_temps[room] = None
                sensor_last_updated[room] = None

            if vals['hum'] is not None:
                measured_humidity[room] = vals['hum'] / 100
                humidity_last_updated[room] = vals['last_updated']
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
        valve_states = {}
        for room, info in rooms.items():
            valve_states_for_room = []
            if isinstance(info["thermostats"], str):
                for th in (t.strip() for t in info["thermostats"].split(";") if t.strip()):
                    valve_states_for_room.append(get_thermostat_state_by_id(th,["valve"])["valve"])
            else:
                if info['thermostats']:
                    valve_states_for_room.append(100)
                else:
                    valve_states_for_room.append(0)

            valve_states[room] = valve_states_for_room

        system_state['valve_states'] = valve_states
        report("Successfully acquired valve states.")
        success = True
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
        system_state['pump_states'] = get_pump_states()

        report("Successfully acquired pump states.")
        success = True
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
    return system_state
#endregion

#region Compare and command
def compare_and_command(heating_switch:dict, system_state:dict):
    """
    Types:
        temp    pres    valve   logic
        1       1       1       aNorm
        1       0       1       aPSD
        0       1       1       aTSD
        0       0       1       aPTSD
        1       0       0       bNorm
        0       0       0       bTSD

    Logic: https://docs.google.com/presentation/d/1JVkR888i549N9s0fq-km47kBXYoeGFToBFRARagczR4/edit?slide=id.g7309d6401d1e61ac_185#slide=id.g7309d6401d1e61ac_185
        Core:
            Give heat to room based on learned presence patterns, actual presence and measured temp.
            If possible, turn on room only, if not, entire cycle.
            Preparatory heating based on warming characteristics.

        Elements: for each controlled room
            > sheet - manually set presence probabilities
            > override - override request, from:
                - QR: set override requests
                - form: freeform override requests
            > presence - integrated current best knowledge of presence probabilities, based on:
                - sheet with decreasing weight since last modification?
                - recorded presence data for room
            > presence with override - presence with overrides pasted over
            > temperature - presence with override mapped to T_min, T_max range, represents the requested temperature settings
                - T_min, T_max: based on warming characteristics from recorded data
            > heating - temperature with preparatory heating based on warming characteristics
                - warming curve: T_end*end_factor + (T_start*start_factor - T_end*end_factor) * np.exp(-t / tau(T_ext))
                - heating constant: tau, in minutes, tau(T_ext) = a + b*T_ext
                - fitted params for each room: a, b, start_factor, end_factor
            > schedule - heating capped to T_max - no_presence_offset
            > condensed schedule - schedule with applied actual presence input:
                - if presence at time t_pres and t - t_pres > presence_min, add offset for t_pres + presence_persistence hours
                - saved locally
                - posted to Firebase
            > measured temp: primary: sensor, secondary: valve
            > commands:
                - if room has valve and valve is available:
                    - compare valve set temp to c. schedule, update valve if different
                    - send measured room temp to valve
                    - sync heating with valves
                    Rooms:
                        - for each room collect demand on given cycle
                        - if max(demand) > d_on%: pump vote 1
                        - if d_off% < max(demand) < d_on%: pump vote is current state of pump
                        - if max(demand) < d_off%: pump vote 0
                - else: usual voting logic for pump & boiler: if at least one room requires heating on a given cycle, the cycle should be turned on and therefore the boiler too.
                    Rooms:
                        - for each room:
                            - if a room is below the set temp it votes with 1 (need to turn pump on)
                            - if a room is in the buffered range, it votes with whatever the current cycle's pump's state is (no opinion)
                            - if a room is above the set temp it votes with 0 (no need to turn pump on)
                Pumps:
                    - for each pump:
                        - if differs from pump state issue command and log decision
                        - unless cycle-wise off is set
                Boiler: if differs from boiler state issue command and log decision

        Cases:
            aNorm: normal control flow for rooms with a valve
                - flow above
            aPSD: degraded control flow with no current presence data for rooms with a valve
                - schedule --> c. schedule step with presumed presence (no_presence_offset is re-added)
                - log degradation error
            aTSD: degraded control flow with no current temp data for rooms with a valve [can only happen if valve is inaccessible]:
                - turn pumps and boiler based on presence with override
                - log degradation error
            [aPTSD: degraded control flow with no current presence and temp data for rooms with a valve [can only happen if valve is inaccessible]:
                - schedule --> c. schedule step with presumed presence (no_presence_offset is re-added)
                - turn pumps and boiler based on presence with override
                - log degradation error] -- NOT A SEPARATE CASE, combination of the above two, handled independently
            bNorm: normal control flow for rooms without a valve
                - flow above but:
                    - no_presence_offset = 0
                    - no valve interaction at the end
            bTSD: degraded control flow with no current temp data for rooms without a valve
                - turn pumps and boiler based on presence with override
                - log degradation error
    """
    report('\nCOMPARING SET TEMPS TO ACTUAL TEMPS TO DETERMINE VOTES')
    success = False
    control = {}
    try:
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

        for room in rooms_info:
            #set_temp = system_state['set_temps'][room]
            set_temp = max(system_state['set_temps'][room],system_state['set_temps_interp'][room])
            hysteresis_buffer = float(heating_config['hysteresis_buffer'])
            measured_temp = system_state['measured_temps'][room]
            sensor_last_updated = system_state['sensor_last_updated'][room]
            set_low = set_temp - hysteresis_buffer
            set_high = set_temp + hysteresis_buffer
            demand = max(system_state['valve_states'][room])
            demand_open_max = int(heating_config['demand_hysteresis_open_max'])
            demand_open_min = int(heating_config['demand_hysteresis_open_min'])
            demand_close = int(heating_config['demand_hysteresis_close'])
            error_max = float(heating_config['error_max'])
            error_min = float(heating_config['error_min'])

            thermostats = rooms_info[room]["thermostats"].split(";") if isinstance(rooms_info[room]["thermostats"], str) else False
            room_vote = 0
            reason = 'None given'
            reason_control = 'none'
            minutes_since_update = round((datetime.now() - datetime.strptime(sensor_last_updated,settings['timestamp_format'])).total_seconds()/60) if sensor_last_updated else None
            relation = f"{measured_temp} °C, {minutes_since_update} mins ago" if minutes_since_update else f"time controlled room"
            cycle = room_to_cycle(room)
            set_PID = None
            PID_log[room] = {}

            if minutes_since_update and int(heating_config['temp_data_expiry']) < minutes_since_update:
                set_temp = 0 if set_temp <= int(heating_config[f'room_{room}_threshold_temp']) else 1 # Turn set temp to binary on/off
                relation = f"data expired, last data {minutes_since_update} mins ago"

            if set_temp != -1 and heating_switch['cycles'][cycle] == 0: # Cycle is room controlled
                if heating_switch['rooms'][room] == 0: # Room is schedule controlled
                    if set_temp in [0,1]: # Room is time controlled or temp sensor degradation
                        if set_temp:
                            room_vote = 1
                            reason = 'Timed on'
                            reason_control = 't_on'
                        else:
                            room_vote = 0
                            reason = 'Timed off'
                            reason_control = 't_off'
                    else: # Room is temp controlled
                        if thermostats: # Room valve data is available
                            error_raw =  set_temp - measured_temp
                            error_pos = max(0, error_raw)

                            """demand_open = min( # Calculate demand on cycle for decision to start or stop water circulation
                                            max(
                                                demand_open_min
                                                + (1 - ((error_pos + error_max) / (error_max - error_min)))
                                                * (demand_open_max - demand_open_min),
                                                demand_open_min
                                            ),
                                            demand_open_max
                                        )"""
                            demand_open = demand_open_min if system_state['room_states'][room] == 0 else demand_close
                            room_overshoot = False

                            bias_report = []
                            thermostat_i = 0
                            for thermostat in thermostats:
                                active_PID_thermostats.add(thermostat)
                                result = calculate_pid_overlay(
                                    set_temp, measured_temp, sensor_last_updated,
                                    system_state['valve_states'][room][thermostat_i],
                                    demand_open, PID_state.get(thermostat), gains,
                                    datetime.now())
                                set_PID = result['setpoint']
                                regime = result['log']['regime']
                                room_overshoot = room_overshoot or result['room_overshoot']
                                bias_report.append(result['log']['outputs']['net_bias'])
                                confirmed = apply_pid_overlay(
                                    thermostat, result, measured_temp, PID_state)
                                pid_commands_confirmed = confirmed and pid_commands_confirmed
                                PID_log[room][thermostat] = result['log']

                                thermostat_i += 1

                            PID_report = f", (error: {format_to_decimals(error_raw, 2)}, {regime}, bias: {[format_to_decimals(bias, 2) for bias in bias_report]})"

                            if  demand < demand_open:
                                room_vote = 0 # Does nothing in current vote-additive logic just included for completeness
                                reason = 'Closed valves'
                                reason_control = 'd_low'
                                relation = f"{demand} < {demand_open} %{PID_report}"
                            elif demand_open < demand:
                                room_vote = 1
                                reason = 'Open valves'
                                reason_control = 'd_high'
                                relation = f"{demand_open} < {demand} %{PID_report}"
                            else:
                                room_vote = system_state['room_states'][room]
                                reason = 'Closed hysteresis' if system_state['room_states'][room] == 0 else 'Open hysteresis'
                                reason_control = 'd_h_off' if system_state['room_states'][room] == 0 else 'd_h_on'
                                relation = f"{demand_close} <= {demand} <= {demand_open} %{PID_report}"
                            if room_overshoot:  # Do not start heating at all if above demand regime
                                room_vote = 0 # Does nothing in current vote-additive logic just included for completeness
                                reason = 'Above set temp'
                                reason_control = 'above'
                                relation = f"{set_temp + PID_OVERSHOOT_VOTE_THRESHOLD} < {measured_temp} {PID_report} °C"
                        else:
                            if  measured_temp < set_low:
                                room_vote = 1
                                reason = 'Below set temp'
                                reason_control = 'below'
                                relation = f"{measured_temp} < {set_low} °C, {minutes_since_update} mins ago"
                            elif set_high < measured_temp:
                                room_vote = 0 # Does nothing in current vote-additive logic just included for completeness
                                reason = 'Above set temp'
                                reason_control = 'above'
                                relation = f"{set_high} < {measured_temp} °C, {minutes_since_update} mins ago"
                            else:
                                room_vote = system_state['room_states'][room]
                                reason = 'Off hysteresis' if system_state['room_states'][room] == 0 else 'On hysteresis'
                                reason_control = 'h_off' if system_state['room_states'][room] == 0 else 'h_on'
                                relation = f"{set_low} <= {measured_temp} <= {set_high} °C, {minutes_since_update} mins ago"
                elif heating_switch['rooms'][room] == 1: #DEV probably useless, remove?
                    room_vote = 1
                    reason = 'Room master ON'
                    reason_control = 'r_m_on'
                elif heating_switch['rooms'][room] == -1:
                    room_vote = 0
                    reason = 'Room master OFF'
                    reason_control = 'r_m_off'
            elif set_temp == -1:
                room_vote = 0
                reason = f"Cycle {cycle} scheduled master OFF"
                reason_control = 'c_s_m_off'
            elif heating_switch['cycles'][cycle] == 1:
                room_vote = 1
                reason = f"Cycle {cycle} master ON"
                reason_control = 'c_m_on'
            elif heating_switch['cycles'][cycle] == -1:
                room_vote = 0
                reason = f"Cycle {cycle} master OFF"
                reason_control = 'c_m_off'

            report(f"\t{reason} ({relation}): {'['+rooms_info[room]['name']+']' if system_state['occupancy'][room] else rooms_info[room]['name']} voting {['OFF','ON'][room_vote]} for cycle {cycle}.",verbose=True)
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
                f"{pump}: {['OFF', 'ON'][state]}"
                for pump, state
                in system_state['pump_states'].items()
            ]) + ".", verbose=True)
        report(f"Boiler vote: {['OFF','ON'][boiler_vote]}",verbose=True)
        report(f"Boiler state: {['OFF','ON'][system_state['boiler_state']]}",verbose=True)

        control['pid_commands_confirmed'] = pid_commands_confirmed
        control['last_updated'] = timestamp()
        system_node.write(control,'control')
        export_dict_as_json(control,'system/control.json')
        success = pid_commands_confirmed
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'voting'},'control/error')
        ServiceException(f"Module error while voting", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'voting'},'control/error')
        ServiceException(f"Unexpected error while voting", severity = 3)

    log({f"success_voting":success})

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
    try:
        commands = load_commands(COMMANDS_PATH)
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

        boiler_switch_success = True
        pumps_switch_successes = []
        for command in latest_unexecuted_commands_past_due:
            if command['device'] == 'boiler':
                boiler_switch_success = set_boiler_state(command['setting'])
                if boiler_switch_success:
                    report(f"Command executed: '{command['device']}': {['OFF','ON'][command['setting']]}.",verbose=True)
                    command['executed'] = True
                    command['execution_timestamp'] = timestamp()
                    system_state['boiler_state'] = command['setting']
            else:
                pumps_switch_successes.append(set_pump_state(command['device'][-1],command['setting']))
                if pumps_switch_successes[-1]:
                    report(f"Command executed: '{command['device']}': {['OFF','ON'][command['setting']]}.",verbose=True)
                    command['executed'] = True
                    command['execution_timestamp'] = timestamp()
                    system_state['pump_states'][command['device'][-1]] = command['setting']

        newly_executed_commands = list(filter(lambda command:command['executed'],latest_unexecuted_commands_past_due))
        still_unexecuted_commands = list(filter(lambda command:not command['executed'],latest_unexecuted_commands_past_due))

        refresh_commands(future_commands + still_unexecuted_commands)
        archive_commands(executed_commands + newly_executed_commands)

        if False not in pumps_switch_successes and boiler_switch_success:
            success = True
    except ModuleException as e:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'execute_commands'},'control/error')
        ServiceException(f"Module error while executing commands", original_exception=e, severity = 3)
    except Exception:
        system_node.write({'last_updated':timestamp(),'error':True,'where':'execute_commands'},'control/error')
        ServiceException(f"Unexpected error while executing commands", severity = 3)

    log({'success_executing_commands':success})

#endregion

#region Export final state

def export_system_state():
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

    heating_switch = acquire_heating_switch()
    system_state = get_system_state()

    if heating_switch['system'] == 0:
        report('Heating is switched off in config file.')

        system_state['mode'] = 'heating_off'

        if settings['on_raspi']:
            try:
                shutdown_heating()
                export_dict_as_json({}, "system/PID_state.json")
            except ModuleException as e:
                system_node.write({'last_updated':timestamp(),'error':True,'where':'shutdown_heating'},'control/error')
                ServiceException(f"Module error while shutting down heating", original_exception=e, severity = 3)
            except Exception:
                system_node.write({'last_updated':timestamp(),'error':True,'where':'shutdown_heating'},'control/error')
                ServiceException(f"Unexpected error while shutting down heating", severity = 3)

        export_system_state()
        exit()

    compare_and_command(heating_switch, system_state)
    execute_commands()
    export_system_state()
