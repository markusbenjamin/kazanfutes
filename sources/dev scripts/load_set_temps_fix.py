import csv
from datetime import datetime, timedelta
import os

data_and_config_folder = 'data_and_config'

def refresh_config_from_safe():
    global cycle_refresh_and_update, cycle_compare_and_command, cycle_control_pumps, cycle_control_albatros, cycle_monitor_CPU_temp 
    global pump_on_lag, pump_off_lag, pump_command_cooldown_time, albatros_on_lag, albatros_off_lag, albatros_command_cooldown_time
    global room_names, no_of_controlled_rooms, day_names, hysteresis_buffers, room_gids
    global external_temp_threshold, CPU_temp_warning, CPU_temp_shutoff, external_temp_validity_threshold

    # Dictionary to temporarily hold values
    config_data = {}

    # Read the safe config
    with open(data_and_config_folder + '/config_safe.csv', 'r', encoding='utf-8-sig') as file:
        reader = csv.reader(file)
        next(reader)  # skip header

        for row in reader:
            config_data[row[0]] = row[1]

    # Assign values
    cycle_refresh_and_update = float(config_data['cycle_refresh_and_update'])
    cycle_compare_and_command = float(config_data['cycle_compare_and_command'])
    cycle_control_pumps = float(config_data['cycle_control_pumps'])
    cycle_control_albatros = float(config_data['cycle_control_albatros'])
    cycle_monitor_CPU_temp = float(config_data['cycle_monitor_CPU_temp'])
    pump_on_lag = float(config_data['pump_on_lag'])
    pump_off_lag = float(config_data['pump_off_lag'])
    pump_command_cooldown_time = max(pump_on_lag, pump_off_lag) + 2
    albatros_on_lag = float(config_data['albatros_on_lag'])
    albatros_off_lag = float(config_data['albatros_off_lag'])
    albatros_command_cooldown_time = max(albatros_on_lag, albatros_off_lag) + 2
    no_of_controlled_rooms = int(config_data['no_of_controlled_rooms'])

    day_names = {1: 'Hétfő', 2: 'Kedd', 3: 'Szerda', 4: 'Csütörtök', 5: 'Péntek', 6: 'Szombat', 7: 'Vasárnap'}

    # Populate room_names
    room_names = {}
    for i in range(1, no_of_controlled_rooms+1):
        key = f'room_{i}'
        room_names[i] = config_data[key]
    
    # Populate room_gids
    room_gids = {}
    for i in range(1, no_of_controlled_rooms+1):
        key = f'room_{i}_gid'
        room_gids[i] = config_data[key]

    # Populate hysteresis_buffers
    hysteresis_buffers = {}
    for i in range(1, no_of_controlled_rooms+1):
        hysteresis_buffers[i] = {
            "lower": float(config_data[f'buffer_lower_{i}']),
            "upper": float(config_data[f'buffer_upper_{i}'])
        }

    external_temp_threshold = float(config_data['external_temp_threshold'])
    external_temp_validity_threshold = float(
        config_data['external_temp_validity_threshold'])*60
    CPU_temp_warning = float(config_data['CPU_temp_warning'])
    CPU_temp_shutoff = float(config_data['CPU_temp_shutoff'])

def load_csv_file(filename):
    data = []
    with open(filename, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter=',')
        for row in reader:
            try:
                data.append([float(cell) for cell in row])
            except ValueError:
                # Handle rows with non-numeric data or just pass to skip them
                pass
    return data

def load_schedules():
    schedules = {}

    # Generate the list of filenames based on room_names values
    schedule_files = [
        os.path.join(data_and_config_folder, f'schedule_{room_name}.csv')
        for room_name in room_names.values()
    ]

    for schedule_file in schedule_files:
        room_name = os.path.basename(schedule_file).split('_')[
            1].replace('.csv', '')
        schedule_array = load_csv_file(schedule_file)

        # Assuming you want to map room numbers to their schedules
        for key, value in room_names.items():
            if room_name == value:
                schedules[key] = schedule_array

    return schedules

def load_override_commands():
    # The structure of override commands: command_time_str, room, start_date, start_hour, duration, temp
    override_commands = []
    with open(data_and_config_folder + '/override_commands.csv', 'r', encoding='utf-8-sig') as f:
        csv_reader = csv.reader(f)
        for row in csv_reader:
            # Convert room names to room numbers
            room_str = row[1]
            for key, value in room_names.items():
                if room_str == value:
                    row[1] = str(key)
                    break

            command_time_str, room, start_date, start_hour, duration, temp = row
            override_commands.append(row)
    return override_commands

def get_current_time():
    now = datetime.now()
    return [now.year, now.month, now.day, now.weekday() + 1, now.hour, now.minute]

def determine_set_temps_for_room():
    global no_of_controlled_rooms, room_names
    schedules = load_schedules()
    override_commands = load_override_commands()

    current_time_values = get_current_time()
    current_time = datetime(current_time_values[0], current_time_values[1], current_time_values[2], current_time_values[4], current_time_values[5])

    scheduled_temps = {}
    for room in range(1, no_of_controlled_rooms):
        if room in schedules:
            schedule = schedules[room]
            current_row = current_time.hour
            # Python's weekday() is already 0-indexed (Monday = 0)
            current_day = current_time.weekday()
            scheduled_temps[room] = schedule[current_row][current_day]

            # Override logic: Check if there is a valid override command for the current room and time
            latest_cmd_time = datetime.min
            latest_temp = None
            # Track if a newer clear command has been found after a temp command
            clear_override_after_temp = False

            for cmd in override_commands:
                cmd_issue_time = datetime.strptime(cmd[0], '%d/%m/%Y %H:%M:%S')
                cmd_start_time = datetime.strptime(f"{cmd[2]} {cmd[3]}", '%d/%m/%Y %H')
                print(f"{cmd[2]} {cmd[3]}")
                cmd_duration = int(cmd[4])
                cmd_end_time = cmd_start_time + timedelta(hours=cmd_duration)
                cmd_temp = cmd[5]

                if room == int(cmd[1]) and cmd_start_time <= current_time < cmd_end_time:
                    if cmd_temp == "-1" and cmd_issue_time > latest_cmd_time:
                        clear_override_after_temp = True
                        latest_cmd_time = cmd_issue_time
                    elif cmd_temp != "-1" and cmd_issue_time > latest_cmd_time:
                        latest_cmd_time = cmd_issue_time
                        latest_temp = int(cmd_temp)
                        clear_override_after_temp = False

            if not clear_override_after_temp and latest_temp is not None:
                scheduled_temps[room] = latest_temp
                print("\tActive override found for " + room_names[room])
            else:
                print("\tNo active override found for " + room_names[room])
    return scheduled_temps

refresh_config_from_safe()
set_temps = determine_set_temps_for_room()

print(set_temps)