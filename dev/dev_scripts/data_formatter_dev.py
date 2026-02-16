"""
Formats various raw data logs into D3 digestible JSON arrays.

Data types:
- daily measurements for each room (temperature, humidity)
- daily set temps for each room
- daily external temp
- daily gas consumption
- daily heating state (boiler, pumps, rooms)
- daily heat delivery for each cycle -- to be done
"""

#region Init

from utils.project import *

parse_old_logs = False
settings['dev'] = True

export_path_prefix = ""

if settings['dev']:
    settings['verbosity'] = False
    settings['log'] = False
    export_path_prefix = 'dev/'

#endregion

#region Run parameters
"""
Digestion days, data types.
"""

if parse_old_logs:
    start_date = datetime(2024, 11, 15)
    end_date = datetime.now()
    digestion_days = []
    current_date = start_date
    while current_date <= end_date:
        digestion_days.append(current_date)
        current_date += timedelta(days=1)
else:
    digestion_days = [datetime.now()]

#data_types_to_digest = ['room_measurements','room_set_temps','room_overrides','external_temp','gas_consumption','heating_state']
data_types_to_digest = ['room_measurements']

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
                        formatted_entry.update({'room_states':raw_entry['room_votes']})
                    if 'pump_votes' in raw_entry:
                        formatted_entry.update({'cycle_states':raw_entry['pump_votes']})
                    if 'boiler_vote' in raw_entry:
                        formatted_entry.update({'boiler_state':raw_entry['boiler_vote']})
                else:
                    if 'room_states' in formatted_entry and formatted_entry not in formatted_data:
                        formatted_data.append(formatted_entry)
                    
                    # Reset iteration vals
                    current_timestamp = raw_entry['timestamp']
                    formatted_entry = {'timestamp':raw_entry['timestamp']}
            
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