"""
The only continuously running script. If fails, gets restarted by corresponding service file.

Listens to Firebase and refreshes heating control config, schedules and overrides.
Generates condensed schedule (weekly schedule + overrides) for next n days based on latest info got.
If successful, uploads condensed schedule to Firebase.

Usual logging and reporting.
"""

from utils.project import *
settings['verbosity'] = False

#region Initialize settings and else
report('\nINITIALIZE')
rooms_info = get_rooms_info()

heating_config = load_json_to_dict('config/heating_control_config.json')
heating_config_update_info = {'update_needed':True,'last_updated':None}

update_needed = {'weekly_cycle':{},'override_rooms':True,'override_cycles':True}
last_update = {'weekly_cycle':{},'override_rooms':None,'override_cycles':None}
update_urls = {
    'weekly_cycle':{},
    'override_rooms':heating_config['override_rooms_url'],
    'override_cycles':heating_config['override_cycles_url']
    }
local_scheduling_files_relative_path = 'config/scheduling/local_scheduling_files'
export_paths = {
    'weekly_cycle':{},
    'override_rooms':local_scheduling_files_relative_path + '/override_rooms.csv',
    'override_cycles':local_scheduling_files_relative_path + '/override_cycles.csv'
    }
for room in rooms_info:
    update_needed['weekly_cycle'][room] = False
    last_update['weekly_cycle'][room] = None
    update_urls['weekly_cycle'][room] = f"{heating_config['weekly_schedule_url']}&gid={rooms_info[room]['schedule_gid']}"
    export_paths['weekly_cycle'][room] = f"config/scheduling/local_scheduling_files/weekly_cycle_room_{room
    }.csv"

condensed_schedule_update_info = {'update_needed':True,'last_updated':None}
#endregion

#region Update local copy of heating control config
def update_local_heating_control_config():
    report('\nUPDATE HEATING CONFIG')
    if heating_config_update_info['update_needed']:
        success = False
        try:
            heating_control_config_online_version = transpose_2D_array(select_subtable_from_table(download_csv_to_2D_array(heating_config['heating_control_config_url']),[1,-0]))
            updated_heating_config =dict(zip(heating_control_config_online_version[0], heating_control_config_online_version[1]))
            export_dict_as_json(updated_heating_config,'config/heating_control_config.json')
            heating_config_update_info['update_needed'] = False
            heating_config_update_info['last_updated'] = datetime.now()
            update_node.write({'seen_by_updater':True},'heating_control_config')
            success = True
            report("Successfully updated local heating control config.")
            return updated_heating_config
        except ModuleException as e:
            ServiceException(f"Module error while trying to update local heating control config", original_exception=e, severity = 2)
        except Exception:
            ServiceException(f"Unexpected error while trying to update local heating control config", severity = 2)
        
        log({f"success_update_local_heating_control_config":success})
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
    # Nem jó a path reference, a Fb-n szoba névvel van, az itteni dictekben pedig szoba szám
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

schedule_node = JSONNodeAtURL(node_relative_path='schedule') # Will have: condensed_schedule, condensed_schedule_last_update, cycle_override_schedule (or something to that effect)
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
        report("Checking if updates are due to expiry.")
        for last_update_info in flatten_dict(last_update):
            update_path = list(last_update_info.keys())[0]
            update_time = list(last_update_info.values())[0]
            if update_time:
                if duration < (datetime.now() - update_time).total_seconds()/(60*60):
                    update_nested_dict(update_needed,update_path,True)
            else:
                update_nested_dict(update_needed,update_path,True)
        if 0<len(find_val_in_dict(update_needed,True)):
            report(f"Update needed at: {find_val_in_dict(update_needed,True)}", verbose=True)
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while checking if updates are due to expiry", original_exception=e, severity = 2)
    except Exception:
        ServiceException(f"Unexpected error while checking if updates are due to expiry", severity = 2)
    
    log({f"success_update_expiry_check":success})

def update_local_scheduling_files():
    report('\nUPDATE LOCAL SCHEDULING FILES')
    for update_path in find_val_in_dict(update_needed, True):
        success = False
        try:
            update_url = read_nested_dict(update_urls,update_path)
            export_path = read_nested_dict(export_paths,update_path)
            export_2D_array_to_csv(download_csv_to_2D_array(update_url),export_path)
            update_nested_dict(update_needed,update_path,False)
            update_nested_dict(last_update,update_path,datetime.now())
            condensed_schedule_update_info['update_needed'] = True

            success = True
            update_keys = update_path.split('/')
            if 'weekly_cycle' in update_keys:
                update_node.write({'seen_by_updater':True},f'weekly_cycle/{rooms_info[update_keys[1]]['name']}')
                report(f'Successfully updated local copy of weekly_cycle/{rooms_info[update_keys[1]]['name']}.')
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
"""
def generate_condensed_schedule(for_how_many_days : int):
    report('\nGENERATE CONDENSED SCHEDULE')
    if condensed_schedule_update_info['last_updated']:
        if condensed_schedule_update_info['last_updated'].day != datetime.now().day:
            condensed_schedule_update_info['update_needed'] = True 
    if condensed_schedule_update_info['update_needed']:
        success = False
        try:
            override_commands_for_rooms = response_table_to_dict_list(
                select_subtable_from_table(load_csv_to_2D_array(local_scheduling_files_relative_path + '/override_rooms.csv'),row_selection=[1,-0]),
                ["timestamp","room_name","date","hour_of_day","duration","temp"]
                )
            rooms_list = list(rooms_info.keys())

            condensed_schedule = {}

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
                        weekly_table = transpose_2D_array(select_subtable_from_table(
                            load_csv_to_2D_array(f"{local_scheduling_files_relative_path}/weekly_cycle_room_{room}.csv"),
                            row_selection=[1,-0],
                            col_selection=[1,-0]
                            ))
                        set_temp = int(weekly_table[timepoint_info['day_of_week']-1][hour_of_day])
                        relevant_room_overrides = [
                            command['temp']
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
                        if 0<len(relevant_room_overrides): # if at least one valid override
                            set_temp = int(relevant_room_overrides[-1]) # select latest
                        update_nested_dict(condensed_schedule,'/'.join([room,str(timepoint_info['unix_day']),str(hour_of_day)]),set_temp)

            condensed_schedule_update_info['update_needed'] = False
            condensed_schedule_update_info['last_updated'] = datetime.now()
            report('Successfully generated condensed schedule.')
            success = True
            return condensed_schedule
        except ModuleException as e:
            ServiceException(f"Module error while trying to generate condensed schedule", original_exception=e, severity = 3)
        except Exception:
            ServiceException(f"Unexpected error while trying to generate condensed schedule", severity = 3)

        log({f"success_generating_condensed_schedule":success})

#endregion

#region Export condensed schedule locally
def export_condensed_schedule_locally(condensed_schedule:dict):
    report('\nEXPORT CONDENSED SCHEDULE')
    success = False
    try:
        export_dict_as_json(condensed_schedule,'config/scheduling/condensed_schedule.json')
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
        success = True
        report("Successfully updated condensed schedule on Firebase.")
    except ModuleException as e:
        ServiceException(f"Module error while trying to update condensed schedule to Firebase", original_exception=e, severity = 2)
    except Exception:
        ServiceException(f"Unexpected error while trying to update condensed schedule to Firebase", severity = 2)

    log({f"success_update_condensed_schedule_to_firebase":success})
#endregion

if __name__ == "__main__":
    while True:
        updated_heating_config = update_local_heating_control_config()
        if updated_heating_config:
            heating_config = updated_heating_config
        check_scheduling_files_expiry(6) # Refresh files older than 6 hours, no matter what
        update_local_scheduling_files()
        condensed_schedule = generate_condensed_schedule(7) # Generate condensed schedule for the following week
        if condensed_schedule:
            export_condensed_schedule_locally(condensed_schedule)
            update_condensed_schedule_on_firebase(condensed_schedule)
        if settings['dev']:
            exit()
        else:
            time.sleep(10)