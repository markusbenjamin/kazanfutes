"""
The only continuously running script. If fails, gets restarted by corresponding service file.

Listens to Firebase and refreshes heating control config, schedules and overrides.
Generates condensed schedule (weekly cycle + overrides) for next n days based on latest info got.
If successful, uploads condensed schedule to Firebase.

Usual logging and reporting.
"""

from utils.project import *

export_path_prefix = ""
#export_path_prefix = "dev/"

#region Initialize settings and else
report('\nINITIALIZE')
startup_time = time.time()
rooms_info = get_rooms_info()

heating_config = load_json_to_dict(f'{export_path_prefix}config/heating_control_config.json')
heating_config_update_info = {'update_needed':True,'last_updated':None}

update_needed = {'weekly_cycle':{},'override_rooms':True,'override_rooms_qr':True,'override_cycles':True}
last_update = {'weekly_cycle':{},'override_rooms':None,'override_rooms_qr':None,'override_cycles':None}
update_ids = {
    'weekly_cycle':{},
    'override_rooms':heating_config['override_rooms_id'],
    'override_rooms_qr':heating_config['override_rooms_qr_id'],
    'override_cycles':heating_config['override_cycles_id']
    }
update_sheet_names = {
    'weekly_cycle':{},
    'override_rooms':None,
    'override_rooms_qr':None,
    'override_cycles':None
    }
local_scheduling_files_relative_path = f'{export_path_prefix}config/scheduling/local_scheduling_files'
export_paths = {
    'weekly_cycle':{},
    'override_rooms':local_scheduling_files_relative_path + '/override_rooms.csv',
    'override_rooms_qr':local_scheduling_files_relative_path + '/override_rooms_qr.csv',
    'override_cycles':local_scheduling_files_relative_path + '/override_cycles.csv'
    }
for room in rooms_info:
    update_needed['weekly_cycle'][room] = False
    last_update['weekly_cycle'][room] = None
    update_ids['weekly_cycle'][room] = heating_config['weekly_cycle_id']
    update_sheet_names['weekly_cycle'][room] = rooms_info[room]['name']
    export_paths['weekly_cycle'][room] = f"{export_path_prefix}config/scheduling/local_scheduling_files/weekly_cycle_room_{room}.csv"

schedule = None
presence_with_override = None
schedule_update_info = {'update_needed':True,'last_updated':None}
#endregion

#region Set up Firebase
def update_detected(relative_path,change_contents):
    """
    Custom callback for changes on update node.
    Sets the update_needed dict accordingly.
    """
    change = change_contents[0]
    report(f"Update detected at {change['path']}: {change['data']}")
    report(f"Setting {update_needed,change['path']} to True.",verbose=True)
    update_keys = change['path'].split('/')
    if 'heating_control_config' in update_keys:
        heating_config_update_info['update_needed'] = True
    else:
        if 'weekly_cycle' in update_keys:
            room = room_name_to_num(update_keys[1])
            update_nested_dict(update_needed,f'weekly_cycle/{room}',True)
        else:
            update_nested_dict(update_needed,change['path'],True)

update_node = JSONNodeAtURL(node_relative_path='update')
update_node.poll_periodically(interval=5,callback=update_detected)

schedule_node = JSONNodeAtURL(node_relative_path=f'{export_path_prefix}schedule') # Will have: condensed_schedule, condensed_schedule_last_update, cycle_override_schedule (or something to that effect)

system_node = JSONNodeAtURL(node_relative_path='system')
#endregion

#region Update local copy of heating control config
def update_local_heating_control_config():
    if heating_config_update_info['update_needed']:
        report('\nUPDATE HEATING CONFIG')
        success = False
        try:
            old_no_presence_offset =  heating_config['no_presence_offset']
            old_heating_window = heating_config['heating_window']
            heating_control_config_online_version = transpose_2D_array(select_subtable_from_table(download_google_sheet_to_2D_array(heating_config['heating_control_config_id']),[1,-0],[0,-1]))
            updated_heating_config = dict(zip(heating_control_config_online_version[0], heating_control_config_online_version[1]))
            export_dict_as_json(updated_heating_config,f'{export_path_prefix}config/heating_control_config.json')
            new_no_presence_offset =  heating_config['no_presence_offset']
            new_heating_window = heating_config['heating_window']
            if old_no_presence_offset != new_no_presence_offset or old_heating_window != new_heating_window:
                schedule_update_info['update_needed'] = True
                        
            heating_config_update_info['update_needed'] = False
            heating_config_update_info['last_updated'] = datetime.now()
            update_node.write({'seen_by_updater':True},'heating_control_config')
            report("Successfully updated local heating control config.")

            generate_and_export_heating_switch(updated_heating_config)
            report("Successfully generated heating switch config.")
            success = True
            return updated_heating_config
        except ModuleException as e:
            ServiceException(f"Module error while trying to update local heating control config", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Unexpected error while trying to update local heating control config", severity = 2)
        
        log({f"success_update_local_heating_control_config":success})
#endregion

#region Update heating switch
"""
Generates a json config file from the heating control table.
"""
def generate_and_export_heating_switch(heating_config:dict = None):
    """
    Returns the various master switch states based on the heating config dict.
    """
    report('\nGENERATE HEATING SWITCH')
    try:
        if not heating_config:
            heating_config = load_json_to_dict('config/heating_control_config.json')
        heating_switch = {}
        heating_switch['system'] = int(heating_config['system_on'])
        heating_switch['cycles'] = {cycle:int(heating_config['cycle_'+str(cycle)+'_on']) for cycle in range(1,5)}
        room_num = len(get_rooms_info())+2
        heating_switch['rooms'] = {room:int(heating_config['room_'+str(room)+'_on']) for room in range(1,room_num)}

        system_node.write(heating_switch,'switch')
        system_node.write({'last_updated':timestamp()},'switch')
        export_dict_as_json(heating_switch,'config/heating_switch.json')
    except Exception:
        ServiceException("Couldn't generate system switch")
#endregion

#region Update local copies of scheduling files (weekly cycles, overrides)
"""
If there is an update or if x time has passed since the last update (store last update externally on disk).
"""
def check_scheduling_files_expiry(duration:float):
    """
    Checks whether the specified duration in hours has passed since the last update on any scheduling file.
    If yes, set the path in update_needed dict accordingly.
    """
    report('\nCHECK SCHEDULING FILES EXPIRY')
    success = False
    try:
        report("Checking if updates are due to expiry.", verbose=True)
        for last_update_info in flatten_dict(last_update):
            update_path = list(last_update_info.keys())[0]
            update_time = list(last_update_info.values())[0]
            if update_time:
                if duration < (datetime.now() - update_time).total_seconds()/(60*60):
                    update_nested_dict(update_needed,update_path,True)
            else:
                update_nested_dict(update_needed,update_path,True)
        if 0<len(find_val_in_dict(update_needed,True)):
            report(f"Update needed at: {find_val_in_dict(update_needed,True)}")
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while checking if updates are due to expiry", original_exception=e, severity = 2)
    except Exception:
        ServiceException(f"Unexpected error while checking if updates are due to expiry", severity = 2)
    
    log({f"success_update_expiry_check":success})

def update_local_scheduling_files():
    for update_path in find_val_in_dict(update_needed, True):
        report('\nUPDATE LOCAL SCHEDULING FILES')
        success = False
        try:
            update_id = read_nested_dict(update_ids, update_path)
            update_sheet_name = read_nested_dict(update_sheet_names, update_path)
            export_path = read_nested_dict(export_paths, update_path)
            export_2D_array_to_csv(download_google_sheet_to_2D_array(update_id,update_sheet_name),export_path)
            update_nested_dict(update_needed,update_path,False)
            update_nested_dict(last_update,update_path,datetime.now())
            schedule_update_info['update_needed'] = True

            success = True
            update_keys = update_path.split('/')
            if 'weekly_cycle' in update_keys:
                update_node.write({'seen_by_updater':True},f'weekly_cycle/{rooms_info[update_keys[1]]["name"]}')
                report(f'Successfully updated local copy of weekly_cycle/{rooms_info[update_keys[1]]["name"]}.')
            else:
                update_node.write({'seen_by_updater':True},update_path)
                report(f'Successfully updated local copy of {update_path}.')
        except ModuleException as e:
            ServiceException(f"Module error while trying to update local copy of {update_path}", original_exception=e, severity = 3)
        except Exception:
            ServiceException(f"Unexpected error while trying to update local copy of {update_path}", severity = 3)

        log({f"success_room_{update_path}_update":success})
#endregion

#region Generate condensed schedule for next n days
"""
If there was an update to either the weekly cycles or the overrides or midnight has passed.

Pipeline:
    - presence with overrides, based on:
        - weighted avearge of weekly cycle in 0/1 format and calculated presence patterns based on past n weeks
        - masked with overrides in temp format (mapped to 0/1)
    - temp, calculated from presence with overrides and Tmin, Tmax for each room
    - heating, calculated from temp by taking into account warming params for each room
    - condensed schedule, calculated from heating by subtracting no presence offset clipped to Tmin
"""
def extract_warming_params():
    # Extract warming params from csv
    warming_params_table = response_table_to_dict_list(
            select_subtable_from_table(load_csv_to_2D_array(f'{export_path_prefix}config/warming_params.csv'),row_selection=[1,-0]),
            ["room_name","a","b","start_factor","end_factor","t_min","t_max"]
            )
    warming_params = {}
    for room_params in warming_params_table:
        warming_params[room_name_to_num(room_params['room_name'])] = {
            'a':float(room_params['a']),
            'b':float(room_params['b']),
            'start_factor':float(room_params['start_factor']),
            'end_factor':float(room_params['end_factor']),
            't_min':float(room_params['t_min']),
            't_max':float(room_params['t_max'])
        }
    return warming_params

def get_presence_patterns_with_weekly_cycle_weighted_average(room, day, hour):
    def sort_nested_dict(node):
        """
        Recursively return a copy of *node* whose dict keys
        that are numeric strings are ordered by their numeric value.
        """
        if not isinstance(node, dict):
            return node

        # sort current level, then recurse
        return {
            k: sort_nested_dict(v)
            for k, v in sorted(node.items(), key=lambda kv: int(kv[0]))
        }

    weekly_cycle = transpose_2D_array(select_subtable_from_table(
        load_csv_to_2D_array(f"{local_scheduling_files_relative_path}/weekly_cycle_room_{room}.csv"),
        row_selection=[1,-0],
        col_selection=[1,-0]
        ))
    
    presence_patterns = load_json_to_dict(f"{export_path_prefix}config/scheduling/local_scheduling_files/occupancy.json")
    presence_pattern = {}

    presence_prob = float(weekly_cycle[int(day)-1][int(hour)])
    if room in presence_patterns:
        presence_pattern = sort_nested_dict(presence_patterns[room])
    
        set_presence = float(weekly_cycle[int(day)-1][int(hour)])
        in_threshold = float(heating_config[f"room_{room}_in_threshold"])
        weekly_cycle_weight = float(heating_config[f"room_{room}_weekly_cycle_weight"])
        presence_prob = max(0, min(1, weekly_cycle_weight * set_presence + (1 - weekly_cycle_weight) * math.floor((presence_pattern[str(day)][str(hour)]/in_threshold))))
    return presence_prob
        
def generate_condensed_schedule(already_existing_presence_with_override = None, already_existing_schedule = None, for_how_many_days:int = 7):
        """
        Adds presence effects to already existing or locally computed schedule to arrive at condensed schedule.
        """
        report('\nGENERATE CONDENSED SCHEDULE')
        success = False
        try:
            if schedule_update_info['last_updated']:
                if schedule_update_info['last_updated'].day != datetime.now().day:
                    schedule_update_info['update_needed'] = True 
            if schedule_update_info['update_needed']:
                schedule_with_pres_with_o = generate_schedule(for_how_many_days)
                schedule = schedule_with_pres_with_o['schedule']
                presence_with_override = schedule_with_pres_with_o['presence_with_override']
                schedule_update_info['update_needed'] = False
                schedule_update_info['last_updated'] = datetime.now()
            else:
                schedule = already_existing_schedule
                presence_with_override = already_existing_presence_with_override
            
            condensed_schedule = presence_enforcer(presence_with_override ,schedule)
            
            success = True
            
            return {
                "presence_with_override":presence_with_override,
                "schedule":schedule, 
                "condensed_schedule":condensed_schedule
                }
        except ModuleException as e:
            ServiceException(f"Module error while trying to generate condensed schedule", original_exception=e, severity = 3)
        except Exception:
            ServiceException(f"Unexpected error while trying to generate condensed schedule", severity = 3)

        log({f"success_generating_condensed_schedule":success})

def generate_schedule(for_how_many_days : int):
    success = False
    try:
        override_commands_for_rooms = [
            command
            for command 
            in response_table_to_dict_list(
                select_subtable_from_table(load_csv_to_2D_array(local_scheduling_files_relative_path + '/override_rooms_qr.csv'),row_selection=[1,-0]),
                ["google_timestamp","room_name","date","hour_of_day","duration","on"]
                )
            if datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H')+timedelta(hours=int(command['duration'])) >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            ] + [
            command
            for command 
            in response_table_to_dict_list(
                select_subtable_from_table(load_csv_to_2D_array(local_scheduling_files_relative_path + '/override_rooms.csv'),row_selection=[1,-0]),
                ["google_timestamp","room_name","date","hour_of_day","duration","on"]
                )
            if datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H')+timedelta(hours=int(command['duration'])) >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            ]

        override_commands_for_cycles = [
            command
            for command 
            in response_table_to_dict_list(
                select_subtable_from_table(load_csv_to_2D_array(local_scheduling_files_relative_path + '/override_cycles.csv'),row_selection=[1,-0]),
                ["google_timestamp","cycle","date","hour_of_day","duration"]
                )
            if datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H')+timedelta(hours=int(command['duration'])) >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            ]
    
        rooms_list = list(rooms_info.keys())

        # Calculate presence with override from presence patterns, weekly cycle and overrides #DEV
        presence_with_override = {}
        for day_from_now in range(0,for_how_many_days):
            shifted_day = datetime.now() + timedelta(days=day_from_now)
            for hour_of_day in range(0,24):
                timepoint = datetime(
                        int(shifted_day.strftime("%Y")),
                        int(shifted_day.strftime("%m")),
                        int(shifted_day.strftime("%d")),
                        hour_of_day,
                        30
                        )
                timepoint_info = generate_timepoint_info(timepoint)
                for room in rooms_list:
                    # Set temp based on presence patterns + weekly cycle weighted average
                    set_temp = get_presence_patterns_with_weekly_cycle_weighted_average(room, timepoint_info['day_of_week'], hour_of_day)
                    
                    # Check if there's a relevant room override, overwrite set temp if yes
                    relevant_room_overrides = [
                        command
                        for command
                        in override_commands_for_rooms
                        if 
                        command['room_name'] == room_num_to_name(room) # room matches
                        and
                        datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H') # start of override period is
                        < # before
                        timepoint # iterated timepoint and iterated timepoint is
                        < # before
                        datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H') + timedelta(hours=int(command['duration'])) # end of override period
                    ]

                    relevant_room_overrides = sorted(relevant_room_overrides, key=lambda command: datetime_object_from_google_timestamp(command['google_timestamp']))

                    if 0<len(relevant_room_overrides): # if at least one valid override
                        set_temp = math.floor(int(relevant_room_overrides[-1]['on'])/17) # select latest, 17 is magic number to split heating on vs. heating off
                    
                    # Check if there's a relevant cycle-wide override, overwrite set temp if yes
                    relevant_cycle_overrides = [
                        -1
                        for command
                        in override_commands_for_cycles
                        if 
                        command['cycle'] == room_to_cycle(room) # room is on cycle
                        and
                        datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H') # start of override period is
                        < # before
                        timepoint # iterated timepoint and iterated timepoint is
                        < # before
                        datetime.strptime(command['date']+'-'+command['hour_of_day'],'%d/%m/%Y-%H') + timedelta(hours=int(command['duration'])) # end of override period
                    ]
                    if 0<len(relevant_cycle_overrides): # if at least one valid override
                        set_temp = 0 # set master off for room
                    update_nested_dict(presence_with_override,'/'.join([room,str(timepoint_info['unix_day']),str(hour_of_day)]),set_temp)        

        # Calculate temp curves for rooms from presence and t_min, t_max
        temp = {}
        for room_num, days_presence in presence_with_override.items():
            temp[room_num] = {}
            for day,presence in days_presence.items():
                temp[room_num][day] = {}
                for hour, val in presence.items():
                    temp[room_num][day][hour] = warming_params[room_num]['t_min']+val*(warming_params[room_num]['t_max'] - warming_params[room_num]['t_min'])


        # Calculate warming curves for rooms from parameters
        warming = lambda t, T1, T2, tau: T2 + (T1 - T2) * math.exp(-t / tau)
        def clamp(x, low, high):
            return max(min(x, high), low)
        external_temp = scrape_external_temperature()
        warming_curve =  {}
        back_hour_num = 7
        for room_num in presence_with_override:
            warming_curve[room_num] = {
                h // 60 - back_hour_num:
                clamp(
                    warming(
                        h,
                        warming_params[room_num]['t_min'] * warming_params[room_num]['start_factor'],
                        warming_params[room_num]['t_max'] * warming_params[room_num]['end_factor'],
                        warming_params[room_num]['a'] + warming_params[room_num]['b'] * external_temp,
                    ),
                    warming_params[room_num]['t_min'],
                    warming_params[room_num]['t_max']
                )
                for h in range(0, back_hour_num * 60 + 1, 60)
                }


        # Calculate heating curves for rooms from warming curves and temp curves
        heating = copy.deepcopy(temp)
        for room_num, days_temp in heating.items():
            warming_items  = list(warming_curve[room_num].items())
            warming_keys = [k for k, _ in warming_items]
            warming_values = [v for _, v in warming_items]
            for day, temps in days_temp.items():
                for h in range(24):
                    set_temp = temps[str(h)]
                    closest_on_warming = min(warming_values, key=lambda t: abs(t - set_temp))
                    this_hour_in_warming = warming_keys[warming_values.index(closest_on_warming)]
                    back_hours = back_hour_num + this_hour_in_warming
                    for b_h in range(1,back_hours+1):
                        warming_key = this_hour_in_warming - b_h
                        if h - b_h >=0:
                            heating[room_num][day][str(h - b_h)] = max(
                                    heating[room_num][day][str(h - b_h)],
                                    warming_curve[room_num][warming_key]
                                )
                        
        # Calculate schedule by subtracting no presence offset
        no_presence_offset = float(heating_config["no_presence_offset"])
        schedule = copy.deepcopy(heating)
        for room_num, room_schedule_for_days in schedule.items():
            for day, room_schedule in room_schedule_for_days.items():
                for h, set_temp in room_schedule.items():
                    enforce_no_presence = 1 if isinstance(rooms_info[room_num]['pres'],str) else 0
                    schedule[room_num][day][h] = round(clamp(
                        schedule[room_num][day][h] - no_presence_offset * enforce_no_presence,
                        warming_params[room_num]['t_min'],
                        warming_params[room_num]['t_max']
                    ),1)

        report('Successfully generated schedule.')
        success = True
        return {'presence_with_override':presence_with_override,'schedule':schedule}
    except ModuleException as e:
        ServiceException(f"Module error while trying to generate schedule", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while trying to generate schedule", severity = 3)

    log({f"success_generating_schedule":success})

def presence_enforcer(presence_with_override, schedule):
    success = False
    condensed_schedule = copy.deepcopy(schedule)
    try:
        # Calculate condensed schedule by enforcing presence effects
        no_presence_offset = float(heating_config["no_presence_offset"])
        heating_window = int(heating_config["heating_window"])
        rooms_occupancy = get_rooms_occupancy(minutes = range(-heating_window,1))
        rooms_aggregate_occupancy_past_n_minutes = {}
        for room, states in transpose_dict(rooms_occupancy).items():
            if True in list(states.values()):
                rooms_aggregate_occupancy_past_n_minutes[room] = True
            elif None in list(states.values()):
                rooms_aggregate_occupancy_past_n_minutes[room] = None
            else:
                rooms_aggregate_occupancy_past_n_minutes[room] = False
        timepoint_info = generate_timepoint_info()
        day = str(timepoint_info['unix_day'])
        h = timepoint_info['hour_of_day']      
        
        for room_num, state in rooms_aggregate_occupancy_past_n_minutes.items():
            if room_num in condensed_schedule and state: # and presence_with_override[room_num][day][str(int(h))] > 0.3: # Give heating if presence regardless of previous patterns
                #condensed_schedule[room_num][day][str(int(h))] += no_presence_offset
                condensed_schedule[room_num][day][str(int(h))] = warming_params[room_num]['t_max']

        report('Successfully generated schedule.')
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while trying to generate schedule", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while trying to generate schedule", severity = 3)
    log({f"success_generating_condensed_schedule":success})
    return condensed_schedule

#endregion

#region Export condensed schedule locally
def export_condensed_schedule_locally(condensed_schedule:dict):
    report('\nEXPORT CONDENSED SCHEDULE')
    success = False
    try:
        export_dict_as_json(condensed_schedule,f'{export_path_prefix}config/scheduling/condensed_schedule.json')
        success = True
        report("Successfully exported condensed schedule.")
    except ModuleException as e:
        ServiceException(f"Module error while trying to export condensed schedule locally", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while trying to export condensed schedule locally", severity = 3)

    log({f"success_export_condensed_schedule_locally":success})
#endregion

#region Update condensed schedule on Firebase
def update_condensed_schedule_on_firebase(condensed_schedule:dict):
    report('\nUPDATE CONDENSED SCHEDULE ON FIREBASE')
    success = False
    try:
        schedule_node.write(condensed_schedule,'condensed_schedule')
        schedule_node.write({'last_updated':timestamp()},'')
        success = True
        report("Successfully updated condensed schedule on Firebase.")
    except ModuleException as e:
        ServiceException(f"Module error while trying to update condensed schedule to Firebase", original_exception=e, severity = 2)
    except Exception:
        ServiceException(f"Unexpected error while trying to update condensed schedule to Firebase", severity = 2)

    log({f"success_update_condensed_schedule_to_firebase":success})
#endregion

#region Update valid requests on Firebase
def update_valid_requests_on_firebase():
    report('\nUPDATE REQUEST LIST ON FIREBASE')
    success = False
    try:
        def keep_latest_entries(entries):
            """Helper."""
            latest_by_time = {}

            for entry in entries:
                time_val = entry["time"]
                current_ts = datetime.strptime(entry["timestamp"], "%Y-%m-%d-%H-%M-%S")
                
                if time_val not in latest_by_time:
                    latest_by_time[time_val] = entry
                else:
                    stored_ts = datetime.strptime(latest_by_time[time_val]["timestamp"], "%Y-%m-%d-%H-%M-%S")
                    if current_ts > stored_ts:
                        latest_by_time[time_val] = entry

            return list(latest_by_time.values())
       
        log_file_path_1 = f"{export_path_prefix}config/scheduling/local_scheduling_files/override_rooms.csv"
        log_file_path_2 = f"{export_path_prefix}config/scheduling/local_scheduling_files/override_rooms_qr.csv"
        action_string = f'updating daily room overrides on Firebase'

        rooms_info = get_rooms_info()

        digestion_day = datetime.now()
        loaded_log_1 = load_csv_to_2D_array(log_file_path_1)
        loaded_log_2 = load_csv_to_2D_array(log_file_path_2)
        
        request_lists = {}
        for room, info in rooms_info.items():
            request_lists_for_room = []
            for raw_entry in itertools.chain(loaded_log_1, loaded_log_2):
                if info['name'] in raw_entry:
                    request_datetime = datetime.strptime(raw_entry[0], "%d/%m/%Y %H:%M:%S")
                    request_timestamp = request_datetime.strftime(settings['timestamp_format'])
                    time_datetime = datetime.strptime(f"{raw_entry[2]}-{raw_entry[3]}", "%d/%m/%Y-%H")
                    time_timestamp = time_datetime.strftime(settings['timestamp_format'])
                    if time_datetime.date() == digestion_day.date():
                        time_timestamp = datetime.strptime(f"{raw_entry[2]}-{raw_entry[3]}", "%d/%m/%Y-%H").strftime(settings['timestamp_format'])
                        formatted_request = {
                            'timestamp': request_timestamp,
                            'time': time_timestamp,
                            'duration': raw_entry[4],
                            'set_temp': warming_params[room]['t_max'] if math.floor(float(raw_entry[5])/17) >= 1 else warming_params[room]['t_min']
                        }
                        request_lists_for_room.append(formatted_request)
            request_lists[room] = keep_latest_entries(request_lists_for_room)
        
        schedule_node.write(request_lists,'request_lists')

        report(f"Done: {action_string}.",verbose=True)
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while {action_string}.", original_exception=e, severity = 2)
    except Exception:
        ServiceException(f"Module error while {action_string}.", severity = 2)

    # Log execution
    log({f"success {action_string}":success})
#endregion

if __name__ == "__main__":
    settings['dev'] = False
    if settings['dev']:
        settings['verbosity'] = True
        settings['log'] = False

    while True:
        updated_heating_config = update_local_heating_control_config()
        if updated_heating_config:
            heating_config = updated_heating_config
        warming_params = extract_warming_params()
        check_scheduling_files_expiry(6) # Refresh files older than 6 hours, no matter what
        update_local_scheduling_files()
        pres_with_o_schedule_and_condensed_schedule = generate_condensed_schedule(presence_with_override, schedule, 7) # Generate condensed schedule for the following week
        presence_with_override = pres_with_o_schedule_and_condensed_schedule['presence_with_override'] # No current presence effects
        schedule = pres_with_o_schedule_and_condensed_schedule['schedule'] # No current presence effects
        condensed_schedule = pres_with_o_schedule_and_condensed_schedule['condensed_schedule'] # Current presence effects added
        if condensed_schedule:
            export_condensed_schedule_locally(condensed_schedule)
            update_condensed_schedule_on_firebase(condensed_schedule)
            update_valid_requests_on_firebase()
        if settings['dev']:
            exit()
        else:
            report('\nSLEEPING FOR 10 SECS')
            time.sleep(10)
        if time.time() - startup_time >= 1*1800:
            exit()