"""
Formats various raw data logs into D3 digestible JSON arrays.

Data types:
- daily measurements for each room (temperature, humidity)
- daily set temps for each room
- daily list of overrides for given day (not by issuance)
- daily KPIs for rooms
- daily external temp from WS90 observations
- daily gas consumption
- daily heating state (boiler, pumps, rooms)
- daily pump powers
- daily boiler plug power and executed boiler commands
- daily supply-water temperature for each cycle
- daily valve opening state for each room
"""

#region Init

from utils.project import *
from utils.water_temperature_formatter import format_cycle_water_temperatures
from utils.boiler_power_formatter import format_boiler_power, format_boiler_commands
from utils.external_temperature_formatter import format_ws90_external_temperatures, format_ws90_weather
from utils.heat_delivery_formatter import format_cycle_heat_delivery
from utils.room_environment_formatter import format_room_environment
from utils.room_control_kpi_formatter import format_room_control_kpis
from utils.radiator_formatter import format_radiator_temperatures, format_radiator_valves

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
    data_types_to_digest = ['room_measurements','room_environment','room_set_temps','room_overrides','external_temp','weather_station','gas_consumption','heating_state','room_valve_states','room_kpis','room_control_kpis','pumps_power','cycle_water_temps','cycle_heat_delivery','boilers_power','radiators']

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

    #region Room environmental plots
    if 'room_environment' in data_types_to_digest:
        success = False
        action_string = f'formatting daily room environmental plots for {digestion_daystamp}'
        try:
            source_logs = []
            for relative_path in ('data/logs/aqara_and_nous/aqara_and_nous.json',
                                  'data/logs/service_execution/heating_control/heating_control.json'):
                source_path = relative_path + log_file_suffix
                source_logs.append(load_ndjson_to_json_list(source_path)
                                   if os.path.exists(os.path.join(get_project_root(), source_path)) else [])
            occupancy_path = 'config/scheduling/local_scheduling_files/occupancy.json'
            occupancy_patterns = load_json_to_dict(occupancy_path) if os.path.exists(os.path.join(get_project_root(), occupancy_path)) else {}
            formatted_rooms = format_room_environment(*source_logs, digestion_daystamp, get_rooms_info(just_controlled=False),
                                                       occupancy_patterns=occupancy_patterns)
            for room, formatted_data in formatted_rooms.items():
                export_json_list_to_json_file(formatted_data,
                    f'{export_path_prefix}data/formatted/{digestion_daystamp}/room_{room}_environment.json')
            report(f'Done: {action_string}.', verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f'Module error while {action_string}.', original_exception=e, severity=2)
        except Exception:
            ServiceException(f'Unexpected error while {action_string}.', severity=2)
        log({f'success {action_string}': success})
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
        log_file_path = r"data/logs/weather_station/weather_station.json"
        action_string = f'formatting external temp for {digestion_daystamp}'

        try:
            source_path = f"{log_file_path}{log_file_suffix}"
            loaded_log = load_ndjson_to_json_list(source_path) if os.path.exists(os.path.join(get_project_root(), source_path)) else []
            formatted_data = format_ws90_external_temperatures(loaded_log, digestion_daystamp)
            
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

    #region WS90 weather selector
    if 'weather_station' in data_types_to_digest:
        success = False
        action_string = f'formatting WS90 weather for {digestion_daystamp}'
        try:
            source_path = f'data/logs/weather_station/weather_station.json{log_file_suffix}'
            loaded_log = load_ndjson_to_json_list(source_path) if os.path.exists(os.path.join(get_project_root(), source_path)) else []
            formatted_data = format_ws90_weather(loaded_log, digestion_daystamp)
            export_json_list_to_json_file(formatted_data, f'{export_path_prefix}data/formatted/{digestion_daystamp}/weather_station.json')
            report(f'Done: {action_string}.', verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f'Module error while {action_string}.', original_exception=e, severity=2)
        except Exception:
            ServiceException(f'Unexpected error while {action_string}.', severity=2)
        log({f'success {action_string}': success})
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

    #region Boiler plug power and executed heating commands
    if 'boilers_power' in data_types_to_digest:
        success = False
        action_string = f'formatting boiler plug power for {digestion_daystamp}'
        try:
            log_file_path = f'data/logs/boilers_power/boiler_plugs.json{log_file_suffix}'
            loaded_log = load_ndjson_to_json_list(log_file_path) if os.path.exists(os.path.join(get_project_root(), log_file_path)) else []
            formatted_plugs = format_boiler_power(loaded_log, digestion_daystamp)
            for plug, readings in formatted_plugs.items():
                export_json_list_to_json_file(readings, f'{export_path_prefix}data/formatted/{digestion_daystamp}/{plug}_power.json')
            commands_path = 'data/heating_control/commands_archive.json'
            commands = load_json_to_dict(commands_path) if os.path.exists(os.path.join(get_project_root(), commands_path)) else []
            export_json_list_to_json_file(
                format_boiler_commands(commands, digestion_daystamp),
                f'{export_path_prefix}data/formatted/{digestion_daystamp}/boiler_commands.json'
            )
            report(f'Done: {action_string}.', verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f'Module error while {action_string}.', original_exception=e, severity=2)
        except Exception:
            ServiceException(f'Unexpected error while {action_string}.', severity=2)
        log({f'success {action_string}': success})
    #endregion

    #region Cycle water temperatures
    if 'cycle_water_temps' in data_types_to_digest:
        success = False
        log_file_path = "data/logs/heat_delivery/heatmeters_state.json"
        action_string = f'formatting daily cycle water temperatures for {digestion_daystamp}'
        try:
            loaded_log = load_ndjson_to_json_list(f"{log_file_path}{log_file_suffix}")
            meter_config = load_json_to_dict('config/heating_monitor.json')['cycles']
            meter_mapping = {str(cycle): meter_config[str(cycle)]['meter'] for cycle in range(1, 5)}
            formatted_per_cycle = format_cycle_water_temperatures(loaded_log, digestion_daystamp, meter_mapping)
            for cycle, formatted_data in formatted_per_cycle.items():
                export_json_list_to_json_file(
                    formatted_data,
                    f"{export_path_prefix}data/formatted/{digestion_daystamp}/cycle_{cycle}_water_temps.json"
                )
            report(f"Done: {action_string}.", verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity=2)
        except Exception:
            ServiceException(f"Unexpected error while {action_string}.", severity=2)
        log({f"success {action_string}": success})
    #endregion

    #region Cycle thermal power and flow
    if 'cycle_heat_delivery' in data_types_to_digest:
        success = False
        source_path = f"data/logs/heat_delivery/heatmeters_state.json{log_file_suffix}"
        action_string = f'formatting daily cycle thermal power and flow for {digestion_daystamp}'
        try:
            loaded_log = load_ndjson_to_json_list(source_path) if os.path.exists(os.path.join(get_project_root(), source_path)) else []
            meter_config = load_json_to_dict('config/heating_monitor.json')['cycles']
            meter_mapping = {str(cycle): meter_config[str(cycle)]['meter'] for cycle in range(1, 5)}
            formatted_per_cycle = format_cycle_heat_delivery(loaded_log, digestion_daystamp, meter_mapping)
            for cycle, formatted_data in formatted_per_cycle.items():
                export_json_list_to_json_file(
                    formatted_data,
                    f"{export_path_prefix}data/formatted/{digestion_daystamp}/cycle_{cycle}_heat_delivery.json"
                )
            report(f"Done: {action_string}.", verbose=True)
            success = True
        except ModuleException as e:
            ServiceException(f"Module error while {action_string}.", original_exception=e, severity=2)
        except Exception:
            ServiceException(f"Unexpected error while {action_string}.", severity=2)
        log({f"success {action_string}": success})
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

    #region Room control tracking KPIs
    if 'room_control_kpis' in data_types_to_digest:
        success = False
        action_string = f'formatting room control KPIs for {digestion_daystamp}'
        try:
            source_path = f'data/logs/service_execution/heating_control/heating_control.json{log_file_suffix}'
            entries = load_ndjson_to_json_list(source_path) if os.path.exists(os.path.join(get_project_root(), source_path)) else []
            formatted_data = format_room_control_kpis(entries, digestion_daystamp, get_rooms_info(just_controlled=False),
                                                      end_time=datetime.now() if digestion_day.date() == datetime.now().date() else None)
            export_json_list_to_json_file(formatted_data,
                f'{export_path_prefix}data/formatted/{digestion_daystamp}/room_control_kpis.json')
            success = True
            report(f'Done: {action_string}.', verbose=True)
        except Exception:
            ServiceException(f'Unexpected error while {action_string}.', severity=2)
        log({f'success {action_string}': success})
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

    #region Per-source radiator telemetry (independent of room valve averages)
    if 'radiators' in data_types_to_digest:
        success = False
        action_string = f'formatting radiator sources for {digestion_daystamp}'
        try:
            mapping = load_json_to_dict('system/radiator_mapping.json')
            probe_log = load_ndjson_to_json_list(f'data/logs/radiator_temps/radiator_temps.json{log_file_suffix}')
            valve_log = load_ndjson_to_json_list(f'data/logs/thermostats/thermostats_state.json{log_file_suffix}')
            probes = format_radiator_temperatures(probe_log, digestion_daystamp, mapping)
            valves = format_radiator_valves(valve_log, digestion_daystamp)
            export_json_list_to_json_file(probes, f'{export_path_prefix}data/formatted/{digestion_daystamp}/radiator_temps.json')
            export_json_list_to_json_file(valves, f'{export_path_prefix}data/formatted/{digestion_daystamp}/radiator_valves.json')
            if not parse_old_logs and digestion_daystamp == datetime.now().strftime('%Y-%m-%d') and valves:
                JSONNodeAtURL(node_relative_path='system').write({'radiator_valves': valves[-1]}, 'state')
            success = True
        except ModuleException as e:
            ServiceException(f'Module error while {action_string}.', original_exception=e, severity=2)
        except Exception:
            ServiceException(f'Module error while {action_string}.', severity=2)
        log({f'success {action_string}': success})
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
