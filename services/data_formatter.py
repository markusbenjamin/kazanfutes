"""
Formats various raw data logs into D3 digestible JSON arrays.

Data types:
- daily measurements for each room (temperature, humidity)
- daily set temps for each room
- daily list of overrides for given day (not by issuance)
- daily KPIs for rooms
- daily external temp
- daily gas consumption
- daily heating state (boiler, pumps, rooms)
- daily pump powers
- daily heat delivery for each cycle -- to be done
- daily valve opening state for each room
"""

#region Init

from utils.project import *

parse_old_logs = False
settings['dev'] = False

export_path_prefix = ""
data_types_to_digest = None
digestion_days = None

if settings['dev']:
    settings['verbosity'] = True
    settings['log'] = False
    export_path_prefix = 'dev/'
    data_types_to_digest = ['pumps_power']
    digestion_days = [datetime(2025, 10, 8),datetime(2025, 10, 9),datetime(2025, 10, 10),datetime(2025, 10, 11),datetime(2025, 10, 12)]
    digestion_days = [datetime.now()]

lock_project_dir(f'{export_path_prefix}data/')

#endregion

#region Run parameters
"""
Digestion days, data types.
"""

if parse_old_logs:
    start_date = datetime(2025, 10, 7)
    end_date = datetime.now()
    digestion_days = []
    current_date = start_date
    while current_date <= end_date:
        digestion_days.append(current_date)
        current_date += timedelta(days=1)
else:
    if not digestion_days:
        digestion_days = [datetime.now()]

if not data_types_to_digest:
    data_types_to_digest = ['room_measurements','room_set_temps','room_overrides','external_temp','gas_consumption','heating_state','room_valve_states','room_kpis','pumps_power']

#endregion

for digestion_day in digestion_days:
    digestion_daystamp = digestion_day.strftime('%Y-%m-%d')
    if parse_old_logs:
        log_file_suffix = f".{digestion_daystamp}"
    else:
        log_file_suffix = ""

    #region Room measurements
    if 'room_measurements' in data_types_to_digest:
        success = False
        log_file_path = "data/logs/temperature_and_humidity/temperature_and_humidity.json"
        action_string = f'formatting daily room measurements for {digestion_daystamp}'

        rooms_info = get_rooms_info(just_controlled=False)

        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")
            for room, info in rooms_info.items():
                formatted_data = []
                
                for log_entry in loaded_log:
                    if room in log_entry and log_entry[room]['temp'] and log_entry[room]['hum']:
                        formatted_entry = {
                            'timestamp':log_entry[room]['last_updated'],
                            'temp':log_entry[room]['temp']/100,
                            'hum':log_entry[room]['hum']/100
                            }
                        if formatted_entry not in formatted_data:
                            formatted_data.append(formatted_entry)
                
                export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/room_{room}_measurements.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Room set temps
    if 'room_set_temps' in data_types_to_digest:
        success = False
        log_file_path = r"data/logs/service_execution/heating_control/heating_control.json"
        action_string = f'formatting daily room set temps for {digestion_daystamp}'

        rooms_info = get_rooms_info()

        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")
            for room, info in rooms_info.items():
                formatted_data = []
                
                for raw_entry in loaded_log:
                    if 'set_temps' in raw_entry:
                        formatted_entry = {
                            'timestamp': raw_entry['timestamp'],
                            'set_temp': raw_entry['set_temps'][room]
                        }
                        if formatted_entry not in formatted_data:
                            formatted_data.append(formatted_entry)
                
                export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/room_{room}_set_temps.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Room overrides
    if 'room_overrides' in data_types_to_digest:
        success = False
        log_file_path_1 = r"config/scheduling/local_scheduling_files/override_rooms.csv"
        log_file_path_2 = r"config/scheduling/local_scheduling_files/override_rooms_qr.csv"
        action_string = f'formatting daily room overrides for {digestion_daystamp}'

        rooms_info = get_rooms_info()

        try:
            loaded_log_1 = load_csv_to_2D_array(log_file_path_1)
            loaded_log_2 = load_csv_to_2D_array(log_file_path_2)
            
            formatted_data = {}
            for room, info in rooms_info.items():
                formatted_room_data = []
                for raw_entry in itertools.chain(loaded_log_1, loaded_log_2):
                    if info['name'] in raw_entry:
                        request_datetime = datetime.strptime(raw_entry[0], "%d/%m/%Y %H:%M:%S")
                        request_timestamp = request_datetime.strftime(settings['timestamp_format'])
                        time_datetime = datetime.strptime(f"{raw_entry[2]}-{raw_entry[3]}", "%d/%m/%Y-%H")
                        time_timestamp = time_datetime.strftime(settings['timestamp_format'])
                        if time_datetime.date() == digestion_day.date():
                            formatted_entry = {
                                'timestamp': request_timestamp,
                                'time': time_timestamp,
                                'duration': raw_entry[4],
                                'set_temp': raw_entry[5]
                            }
                            formatted_room_data.append(formatted_entry)
                formatted_data[room] = formatted_room_data
            #print(f"{export_path_prefix}data/formatted/{digestion_daystamp}/override_requests.json")
            export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/override_requests.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region External temp
    if 'external_temp' in data_types_to_digest:
        success = False
        log_file_path = r"data/logs/external_temp/external_temp.json"
        action_string = f'formatting external temp for {digestion_daystamp}'

        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")

            formatted_data = []
            
            for raw_entry in loaded_log:
                formatted_entry = {
                    'timestamp': raw_entry['timestamp'],
                    'external_temp': raw_entry['external_temp']
                }
                if formatted_entry not in formatted_data:
                    formatted_data.append(formatted_entry)
            
            export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/external_temp.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Gas consumption
    if 'gas_consumption' in data_types_to_digest:
        success = False
        log_file_path = r"data/logs/gas_consumption/gas_relay_turns.json"
        action_string = f'formatting gas consumption for {digestion_daystamp}'

        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")

            formatted_data = []

            total_turns = 0
            turn_start = None
            turn_end = None
            previous_turn_end = None

            for raw_entry in loaded_log:
                if raw_entry['gasmeter_pin_state_change'] == 1:
                    total_turns += 1
                    turn_start = datetime.strptime(raw_entry['timestamp'],settings['timestamp_format'])
                elif turn_start and previous_turn_end:
                    turn_end = datetime.strptime(raw_entry['timestamp'],settings['timestamp_format'])
                    formatted_entry = {
                        'timestamp':raw_entry['timestamp'],
                        'secs_to_turn': (turn_end - turn_start).total_seconds(),
                        'burnt_volume': total_turns * 0.1,
                        'secs_since_last_turn': (turn_end - previous_turn_end).total_seconds(),
                        'burn_rate_in_m3_per_h': 0.1/((turn_end - previous_turn_end).total_seconds()/3600)
                    }
                    formatted_data.append(formatted_entry)
                    previous_turn_end = turn_end
                else:
                    previous_turn_end = datetime.strptime(raw_entry['timestamp'],settings['timestamp_format'])
            
            export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/gas_usage.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Pumps power
    if 'pumps_power' in data_types_to_digest:
        success = False
        log_file_path = r"data/logs/pumps/power.json"
        action_string = f'formatting pumps power for {digestion_daystamp}'
        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")

            formatted_data = []
            last_known_powers = {'1':0,'2':0,'3':0,'4':0}
            for raw_entry in loaded_log:
                formatted_entry = {
                    'cp':False,
                    'timestamp':raw_entry['timestamp']
                }

                formatted_changepoint_entry = {
                    'cp':True,
                    'timestamp': timestamp(timestamp_to_datetime(raw_entry['timestamp']) - timedelta(seconds=10))
                }

                print(f"\n{raw_entry}")

                add_changepoint = False
                for pump in ['1','2','3','4']:
                    formatted_changepoint_entry[f'pump_{pump}_power'] = last_known_powers[pump]
                    print(f"{raw_entry['power'][pump]} - {last_known_powers[pump]}")
                    change_abs = abs(raw_entry['power'][pump] - last_known_powers[pump])
                    if 0 < change_abs:
                        add_changepoint = True
                    print(f"{change_abs}")
                    formatted_entry[f'pump_{pump}_power'] = raw_entry['power'][pump]
                    last_known_powers[pump] = raw_entry['power'][pump]
                
                print(f"{add_changepoint}, {formatted_changepoint_entry}, {formatted_entry}")

                if add_changepoint: 
                    formatted_data.append(formatted_changepoint_entry)
                formatted_data.append(formatted_entry)
            
            export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/pumps_power.json")
            #print(json.dumps(formatted_data,indent=2))
            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Heating state
    if 'heating_state' in data_types_to_digest:
        success = False
        log_file_path = r"data/logs/service_execution/heating_control/heating_control.json"
        action_string = f'formatting heating state for {digestion_daystamp}'

        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")

            formatted_data = []
            
            current_timestamp = None
            formatted_entry = {}
            for raw_entry in loaded_log:

                if raw_entry['timestamp'] == current_timestamp:
                    if 'room_votes' in raw_entry:
                        formatted_entry.update({'room_states': raw_entry['room_votes']})
                    if 'pump_votes' in raw_entry:
                        formatted_entry.update({'cycle_states': raw_entry['pump_votes']})
                    if 'boiler_vote' in raw_entry:
                        formatted_entry.update({'boiler_state': raw_entry['boiler_vote']})
                else:
                    if 'room_states' in formatted_entry and formatted_entry not in formatted_data:
                        formatted_data.append(formatted_entry)

                    # Reset iteration vals
                    current_timestamp = raw_entry['timestamp']
                    formatted_entry = {'timestamp': raw_entry['timestamp']}

                    # process the first record of the new timestamp
                    if 'room_votes' in raw_entry:
                        formatted_entry.update({'room_states': raw_entry['room_votes']})
                    if 'pump_votes' in raw_entry:
                        formatted_entry.update({'cycle_states': raw_entry['pump_votes']})
                    if 'boiler_vote' in raw_entry:
                        formatted_entry.update({'boiler_state': raw_entry['boiler_vote']})

            export_json_list_to_json_file(formatted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/heating_state.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Room KPIs
    if 'room_kpis' in data_types_to_digest:
        success = False
        action_string = f'extracting room KPIs for {digestion_daystamp}'
        data_root_for_day = f"data/formatted/{daystamp(digestion_day)}"

        rooms_info = get_rooms_info()

        try:
            extracted_data = {}
            data_expiry = 30
            cycle_turn_on_and_off_times = {}
            for room, info in rooms_info.items():
                binned_data = {}
                data_types = [
                                {
                                    'access':f"room_{room}_measurements",
                                    'key':'temp'
                                },
                                {
                                    'access':f"room_{room}_set_temps",
                                    'key':'set_temp'
                                },
                                {
                                    'access':'heating_state',
                                    'key':'state'
                                }
                            ]

                interpolated_data = {}
                for data_type in data_types:
                    loaded = load_json_to_dict(f"{data_root_for_day}/{data_type['access']}.json")

                    if data_type['key'] == 'state':
                        data_for_type = sorted([
                            {
                                'min_of_day': (timestamp_to_datetime(d['timestamp']) - digestion_day.replace(hour=0, minute=0, second=0)).total_seconds() / 60,
                                data_type['key']: d['cycle_states'][rooms_info[room]['cycle']]
                            }
                            for d in loaded if 'cycle_states' in d
                        ], key=lambda e: e['min_of_day'])
                    elif data_type['key'] == 'temp':
                        data_for_type = [
                        {
                            'min_of_day':(timestamp_to_datetime(d['timestamp'])-digestion_day.replace(hour=0, minute=0,second =0)).total_seconds()/60,
                            data_type['key']:d['temp']
                        }
                        for d in loaded
                        ]
                    elif data_type['key'] == 'set_temp':
                        data_for_type = [
                            {
                                'min_of_day':(timestamp_to_datetime(d['timestamp'])-digestion_day.replace(hour=0, minute=0,second =0)).total_seconds()/60,
                                data_type['key']:d['set_temp']
                            }
                            for d in loaded
                            ]

                    times = [d['min_of_day'] for d in data_for_type]

                    # Set the maximum allowed gap (in minutes) for using data for interpolation.
                    max_gap = data_expiry

                    interpolation_for_type = {}

                    # Loop over every minute of the day (0 to 1439)
                    for m in range(1440):
                        # Find the insertion position of m in the sorted times.
                        pos = bisect.bisect_left(times, m)
                        
                        # If m is before the first data point or after the last, we cannot interpolate.
                        if pos == 0 or pos == len(times):
                            interpolation_for_type[m] = None
                            continue

                        # The data point immediately before m:
                        left_point = data_for_type[pos - 1]
                        # The data point immediately after (or at) m:
                        right_point = data_for_type[pos]

                        # Check the gap conditions:
                        if (m - left_point['min_of_day'] > max_gap) or (right_point['min_of_day'] - m > max_gap):
                            interpolation_for_type[m] = None
                        else:
                            # Perform linear interpolation:
                            m_left = left_point['min_of_day']
                            m_right = right_point['min_of_day']
                            t_left = left_point[data_type['key']]
                            t_right = right_point[data_type['key']]
                            
                            # Compute the fractional distance between the two data points:
                            factor = (m - m_left) / (m_right - m_left)
                            interpolated_val = t_left + factor * (t_right - t_left)
                            
                            interpolation_for_type[m] = interpolated_val
                    
                    interpolated_data[data_type['key']] = interpolation_for_type

                turn_on_times = 0
                turn_off_times = 0
                daily_degree_hours_above = 0
                daily_degree_hours_below = 0

                bin_width = 1
                bin_step = 1
                valid_minutes = 0
                bin_minutes = bin_width + (0 if bin_width%2 else bin_width)
                last_state = 0
                for min_of_day in range(0, 24 * 60, bin_width):
                    bin_data = {}
                    for data_type in data_types:
                        incoming_data_for_type = []
                        for minute in range(min_of_day-bin_width//2,min_of_day+bin_width//2+1,1):
                            if minute in interpolated_data[data_type['key']]:
                                incoming_data_for_type.append(interpolated_data[data_type['key']][minute])
                    
                        bin_data[data_type['key']] = incoming_data_for_type

                    if not any(mean_without_none(value) is None for value in bin_data.values()):
                        valid_minutes += 1

                        mean_state = mean_without_none(bin_data['state'])
                        mean_temp = mean_without_none(bin_data['temp'])
                        mean_set_temp = mean_without_none(bin_data['set_temp'])
                        mean_comfort_diff = mean_temp - mean_set_temp
                        
                        mean_control_diff = mean_state * mean_comfort_diff
                        if mean_control_diff < -0.5:
                            daily_degree_hours_below += mean_control_diff*bin_minutes/60
                        elif mean_control_diff > 0.5:
                            daily_degree_hours_above += mean_control_diff*bin_minutes/60

                        if last_state == 0 and 0 < mean_state and mean_comfort_diff <= 0.5: # This room would turn the cycle on
                            turn_on_times += 1
                            
                            if info['cycle'] not in cycle_turn_on_and_off_times:
                                cycle_turn_on_and_off_times[info['cycle']] = {}
                            if 'on' not in cycle_turn_on_and_off_times[info['cycle']]:
                                cycle_turn_on_and_off_times[info['cycle']]['on'] = 0
                            cycle_turn_on_and_off_times[info['cycle']]['on'] += 1
                        
                        elif last_state == 1 and mean_state < 1:
                            if mean_comfort_diff - 0.5 <= 0.2: # This room would only now be letting the cycle turn off
                                turn_off_times += 1
                                
                                if info['cycle'] not in cycle_turn_on_and_off_times:
                                    cycle_turn_on_and_off_times[info['cycle']] = {}
                                if 'off' not in cycle_turn_on_and_off_times[info['cycle']]:
                                    cycle_turn_on_and_off_times[info['cycle']]['off'] = 0
                                cycle_turn_on_and_off_times[info['cycle']]['off'] += 1

                        last_state = mean_state

                day_validity_ratio = valid_minutes / (minute_of_day()/bin_step  if digestion_day == datetime.today() else ((24*60)/bin_step))

                extracted_data[room] = {
                    'validity_ratio' : day_validity_ratio,
                    'below' : daily_degree_hours_below,
                    'above' : daily_degree_hours_above,
                    'turn_on_times': turn_on_times#,
                    #'turn_off_times':turn_off_times
                }
                
            for room, kpis in extracted_data.items():
                cycle = rooms_info[room]['cycle']
                kpis['turn_on_ratio'] = kpis['turn_on_times'] / cycle_turn_on_and_off_times[cycle]['on'] if cycle in cycle_turn_on_and_off_times else 0
                #kpis['turn_off_ratio'] = kpis['turn_off_times'] / cycle_turn_on_and_off_times[cycle]['off']  if cycle in cycle_turn_on_and_off_times else 0

            export_json_list_to_json_file(extracted_data,f"{export_path_prefix}data/formatted/{digestion_daystamp}/room_KPIs.json")

            report(f"Done: {action_string}.",verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity = 2)

        # Log execution
        log({f"success {action_string}":success})

    #endregion

    #region Room valve states
    
    if 'room_valve_states' in data_types_to_digest:
        success = False
        log_file_path   = r"data/logs/thermostats/thermostats_state.json"
        action_string   = f'formatting daily room valve states for {digestion_daystamp}'
        rooms_info      = get_rooms_info()

        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")

            # pre-compute valve lists once
            room_valves = {
                room: (info['thermostats'].split(';') if isinstance(info['thermostats'], str)
                    else [info['thermostats']])
                for room, info in rooms_info.items()
            }

            formatted_per_room = {room: [] for room in room_valves}

            for raw in loaded_log:                                    # 1× over the log
                ts     = raw['timestamp']
                states = raw['states']                                # local alias

                for room, v_names in room_valves.items():             # small inner loop
                    tot = 0
                    for vn in v_names:
                        tot += states.get(vn, {'valve': 100 if vn else 0})['valve']
                    mean = (tot / len(v_names)) / 100                 # 0?1 float
                    formatted_per_room[room].append({'timestamp': ts, 'valve': mean})

            # one write per room
            for room, data in formatted_per_room.items():
                export_json_list_to_json_file(
                    data,
                    f"{export_path_prefix}data/formatted/{digestion_daystamp}/room_{room}_valve_state.json"
                )

            report(f"Done: {action_string}.", verbose=True)
            success = True

        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity=2)
        except Exception:
            ServiceException(f"Module error while {action_string}.", severity=2)

        log({f"success {action_string}": success})
    
    #endregion

unlock_project_dir(f'{export_path_prefix}data/')