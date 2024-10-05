"""
Main heating control script.
 Execute commands:
        Load issued commands.
        Go over commands and execute unexecuted past ones.
        Mark and filter successfully executed commands.

    Save state:
        Export and upload current state of system (pump states, room set temps and measured temps, boiler state).

Integrated throughout:
    Verbose reporting.
    Runtime success logging of main tasks.
    Feature logging of system state and decisions.
    Error registration.
    Firebase reporting according to dashboard needs.
"""

from utils.project import *

#region Initialize
report('\nINITIALIZE')
success = False
try:
    rooms = get_rooms_info()
    cycles = get_cycles_info()
    heating_config = load_json_to_dict('config/heating_control_config.json')
    condensed_schedule = load_json_to_dict('config/condensed_schedule.json')
    system_node = JSONNodeAtURL(node_relative_path='system')
    report('Successfully loaded config files and initialized Firebase connection.')
    success = True
except ModuleException as e:
    ServiceException(f"Module error while trying to initialize heating control", original_exception=e, severity = 3)
except Exception:
    ServiceException(f"Unexpected error while trying to initialize heating control", severity = 3)
finally:
    log({f"success_initialize":success})

COMMANDS_PATH = os.path.join(get_project_root(), "data", "heating_control", "commands.json")
COMMANDS_ARCHIVE_PATH = os.path.join(get_project_root(), "data", "heating_control", "commands_archive.json")

#endregion

#region Get and export system state
"""
    Measure actual temps.
    Extract set temps from schedule.
    Get boiler and pump states.
    Log to service log.
    Save to system_state.json.
    Upload to Firebase.
"""

def get_and_export_system_state():
    report('\nACQUIRING SYSTEM STATE')
    system_state = {}

    success = False
    try:
        report("Acquiring measured temps.",verbose=True)
        room_temps_and_humidity = get_room_temps_and_humidity_dev()
        measured_temps = {}
        for room,vals in room_temps_and_humidity.items():
            if vals['temp']:
                measured_temps[room] = vals['temp']/100
            else:
                measured_temps[room] = 0.5 # For non-temp controlled rooms

        system_state['measured_temps'] = measured_temps

        report("Successfully acquired measured temps.")
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while acquiring measured temps", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while acquiring measured temps", severity = 3)
    finally:
        log({f"success_acquire_measured_temps":success})

    success = False
    try:
        report("Acquiring set temps.",verbose=True)
        current_timepoint_info = generate_timepoint_info()
        unix_day = str(current_timepoint_info['unix_day'])
        hour_of_day = str(current_timepoint_info['hour_of_day'])

        set_temps = {}
        for room,schedule_for_days in condensed_schedule.items():
            set_temps[room] = schedule_for_days[unix_day][hour_of_day]
        
        system_state['set_temps'] = set_temps

        report("Successfully acquired set temps.")
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while acquiring set temps", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while acquiring set temps", severity = 3)
    finally:
        log({f"success_acquire_set_temps":success})

    success = False
    try:
        report("Acquiring pump states.",verbose=True)       
        system_state['pump_states'] = get_pump_states()

        report("Successfully acquired pump states.")
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while acquiring pump states", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while acquiring pump states", severity = 3)
    finally:
        log({f"success_acquire_pump_states":success})

    success = False
    try:
        report("Acquiring boiler state.",verbose=True)       
        system_state['boiler_state'] = get_boiler_state()

        report("Successfully acquired boiler state.")
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while acquiring boiler state", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while acquiring boiler state", severity = 3)
    finally:
        log({f"success_acquire_boiler_state":success})
    
    try:
        log(system_state)
        system_node.write(system_state,'state')
        export_dict_as_json(system_state,'data/system_state/state.json')
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while exporting system state", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while exporting system state", severity = 3)
    finally:
        log({f"success_export_system_state":success})
    return system_state
#endregion

#region Compare and command
def compare_and_command(system_state:dict):
    """
    Principle: 
        if at least one room requires heating on a given cycle
        the cycle should be turned on 
        and therefore the boiler too.

    Logic:
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

        Commands:
            - issue in the form of {
                            'issuance_time': time of issuance
                            'due_time': after which it should be executed unless there's a newer command
                            'device':pump1, 2, 3, 4 or boiler
                            'setting':0 or 1
                            'executed':0
                            'execution_time':None
                            }
            - save to data/heating_control/commands.json
    """
    report('\nCOMPARING SET TEMPS TO ACTUAL TEMPS TO DETERMINE VOTES')
    success = False
    try:
        rooms_info = get_rooms_info()
        room_votes = {}
        cycle_votes = {'1':0,'2':0,'3':0,'4':0}
        report('Room votes:',verbose=True)
        for room in rooms_info:
            set_temp = system_state['set_temps'][room]
            hysteresis_buffer = float(heating_config['hysteresis_buffer'])
            measured_temp = system_state['measured_temps'][room]
            set_low = set_temp - hysteresis_buffer
            set_high = set_temp + hysteresis_buffer

            room_vote = 0
            reason = 'none given'
            relation = ''

            if  measured_temp < set_low:
                room_vote = 1
                reason = 'Below set temp'
                relation = f"{measured_temp} < {set_low}"
            elif measured_temp < set_high:
                room_vote = 0 # Does nothing in this logic just included for completeness
                reason = 'Hysteresis'
                relation = f"{set_low} <= {measured_temp} <= {set_high}"
            else:
                room_vote = system_state['pump_states'][room_to_cycle(room)]
                reason = 'Above set temp'
                relation = f"{set_high} < {measured_temp}"
            
            report(f"\t{reason} ({relation}): {rooms_info[room]['name']} voting {['OFF','ON'][room_vote]} for cycle {room_to_cycle(room)}.",verbose=True)
            room_votes[room] = room_vote
            cycle_votes[room_to_cycle(room)] += room_vote
            
        pump_votes = {}
        for cycle,votes in cycle_votes.items():
            pump_votes[cycle] = sign(votes)

        boiler_vote = sign(sum(list(pump_votes.values())))

        log({'room_votes':room_votes})
        log({'cycle_votes':cycle_votes})
        log({'pump_votes':pump_votes})
        log({'boiler_vote':boiler_vote})

        cycles_info = get_cycles_info()
        report(f"Cycle votes:\n\t{
            '\n\t'.join([
            f"{cycles_info[cycle]['name']}: {vote} room wants heating."
            for cycle,vote 
            in cycle_votes.items()
            ])}",verbose=True)
        report(f"Pump votes: {
            ', '.join([
            f"{pump}: {['OFF','ON'][vote]}"
            for pump,vote 
            in pump_votes.items()
            ])}.",verbose=True)
        report(f"Boiler vote: {['OFF','ON'][boiler_vote]}",verbose=True)
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while voting", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while voting", severity = 3)
    finally:
        log({f"success_voting":success})

    report('\nISSUING COMMANDS')
    def issue_command(existing_commands, device:str, delay:float, setting:int):
        due_time = datetime.now() + timedelta(minutes=delay)
        command = {
                    'issuance_timestamp':timestamp(),
                    'due_timestamp':timestamp(due_time),
                    'device':f"pump_{cycle}",
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
            report('Command already issued.',verbose=True)  
    
    success = False
    try:
        existing_commands = load_existing_commands()
        new_commands = []
        cycles_info = get_cycles_info()
        for cycle, info in cycles_info.items():
            if system_state['pump_states'][cycle] != pump_votes[cycle]:
                delay = [3, 0][pump_votes[cycle]] # 3 mins cooloff when turning off a cycle
                (lambda cmd: new_commands.append(cmd) if cmd else None)(issue_command(existing_commands, f'pump_{cycle}', delay, pump_votes[cycle]))
        if system_state['boiler_state'] != boiler_vote:
            (lambda cmd: new_commands.append(cmd) if cmd else None)(issue_command(existing_commands,f'boiler',0,boiler_vote))
        
        all_commands = existing_commands + new_commands
        with open(COMMANDS_PATH, 'w') as f:
            json.dump(all_commands, f, indent=4)
        success = True
    except ModuleException as e:
        ServiceException(f"Module error while issuing commands", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while issuing commands", severity = 3)
    finally:
        log({f"success_issuing_command":success})

def load_existing_commands():
    try:
        if not os.path.exists(COMMANDS_PATH):
            with open(COMMANDS_PATH, 'w') as commands_file:
                json.dump([], commands_file)
        with open(COMMANDS_PATH, 'r') as commands_file:
            return json.load(commands_file)
    except ModuleException as e:
        ServiceException(f"Module error while issuing commands", original_exception=e, severity = 3)
    except Exception:
        ServiceException(f"Unexpected error while issuing commands", severity = 3)
    finally:
        log({f"success_loading_existing_commands":success})

def archive_executed_commands():
    pass
#endregion

#region Execute commands
def execute_commands():
    """
    Simply load commands for pumps and the boiler then execute the latest actual.
    If successful, set executed to True and set execution timestamp.
    """
    pass

def archive_executed_commands():
    """
    Load commands to dict, append to archived_commands.json if executed == True.
    """
    pass

#endregion

if __name__ == '__main__':
    settings['verbosity'] = True #DEV
    settings['dev'] = True #DEV
    
    system_state = get_and_export_system_state()
    compare_and_command(system_state)