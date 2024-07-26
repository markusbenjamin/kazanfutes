# region Imports & set test mode
import argparse
parser = argparse.ArgumentParser(description='Run the script in test mode with --test')
parser.add_argument('--test', action='store_true', help='Run the script in test mode')
args = parser.parse_args()
test = args.test
import csv
import ast
import glob
import time
from datetime import datetime, timedelta
import os
import shutil
import asyncio
import aiohttp
try:
    from pydeconz.gateway import DeconzSession
    import tinytuya
    import RPi.GPIO as GPIO
except:
    print("Couldn't import IO modules.")
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import traceback
import requests
import json
import subprocess
import smtplib
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import logging
from logging.handlers import TimedRotatingFileHandler
import sys
import signal
import traceback
import copy
import sys
sys.path.append('modules/')
import interscript_comm as isc
import argparse
# endregion

# region Config & Startup
run = False #Global flag to set whether the main cycle runs
data_and_config_folder = "data_and_config"
try:
    GPIOpin = 4
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIOpin, GPIO.OUT)
    GPIO.output(GPIOpin, GPIO.LOW)
except:
    print("Couldn't set GPIO up.")
verbose = 1
latest_config_got = False
latest_override_got = False
latest_schedules_got = False
last_config_update = datetime(1990,4,4)
last_override_update = datetime(1990,4,4)
last_schedules_update = datetime(1990,4,4)

def load_config_from_local():
    # Config vars
    global repeat_compare_and_command, repeat_control_pumps, repeat_control_albatros, repeat_monitor_CPU_temp, repeat_git_log_push, repeat_download_retry
    global deconz_disconnect_threshold
    global pump_on_lag, pump_off_lag, albatros_on_lag, albatros_off_lag
    global presence_off_lag, no_presence_min_temp
    global room_names, temp_controlled_rooms, controlled_rooms, day_names, hysteresis_buffers, room_gids
    global external_temp_threshold, CPU_temp_logging, CPU_temp_warning, CPU_temp_shutoff, external_temp_validity_threshold
    global last_update_from_room_tolerance, kisterem_tolerance
    global cycle_master_overrides
    global verbose

    # Runtime vars
    global set_temps, measured_temps, overrides
    global last_issued_pump_command
    global external_temp_allow, last_known_external_temp
    global last_update_from_room, sensor_reachable_in_room, last_presence_detected
    global last_config_update,last_override_update,last_schedules_update

    # Dictionary to temporarily hold values
    config_data = {}

    # Read the safe config
    with open(data_and_config_folder + '/config_safe.csv', 'r', encoding='utf-8-sig') as file:
        reader = csv.reader(file)
        next(reader)  # skip header

        for row in reader:
            config_data[row[0]] = row[1]

    # Assign values
    repeat_compare_and_command = float(config_data['repeat_compare_and_command'])
    repeat_control_pumps = float(config_data['repeat_control_pumps'])
    repeat_control_albatros = float(config_data['repeat_control_albatros'])
    repeat_git_log_push = float(config_data['repeat_git_log_push'])
    repeat_download_retry = float(config_data['repeat_download_retry'])
    repeat_monitor_CPU_temp = float(config_data['repeat_monitor_CPU_temp'])
    deconz_disconnect_threshold = float(config_data['deconz_disconnect_threshold'])
    presence_off_lag = float(config_data['presence_off_lag'])
    no_presence_min_temp = float(config_data['no_presence_min_temp'])
    pump_on_lag = float(config_data['pump_on_lag'])
    pump_off_lag = float(config_data['pump_off_lag'])
    albatros_on_lag = float(config_data['albatros_on_lag'])
    albatros_off_lag = float(config_data['albatros_off_lag'])
    no_of_controlled_rooms = int(config_data['no_of_controlled_rooms'])
    last_update_from_room_tolerance = int(config_data['last_update_from_room_tolerance'])
    kisterem_tolerance = float(config_data['kisterem_tolerance'])
    external_temp_threshold = float(config_data['external_temp_threshold'])
    external_temp_validity_threshold = float(config_data['external_temp_validity_threshold'])*60
    CPU_temp_logging = float(config_data['CPU_temp_logging'])
    CPU_temp_warning = float(config_data['CPU_temp_warning'])
    CPU_temp_shutoff = float(config_data['CPU_temp_shutoff'])
    verbose = int(config_data['verbose'])

    # Populate room vars
    room_names = {}
    temp_controlled_rooms = []
    controlled_rooms = []
    set_temps = {}
    measured_temps = {}
    overrides = {}
    last_update_from_room = {}
    sensor_reachable_in_room = {}
    room_gids = {}
    hysteresis_buffers = {}
    for room in range(1, no_of_controlled_rooms+1):
        set_temps[room] = None
        if int(config_data[f'room_{room}_temp_controlled']) == 1:
            temp_controlled_rooms.append(room)
        controlled_rooms.append(room)
        measured_temps[room] = None
        overrides[room] = 0
        last_update_from_room[room] = None
        sensor_reachable_in_room[room] = None
        room_names[room] = config_data[f'room_{room}']
        room_gids[room] = config_data[f'room_{room}_gid']
        hysteresis_buffers[room] = {
            "lower": float(config_data[f'buffer_lower_{room}']),
            "upper": float(config_data[f'buffer_upper_{room}'])
        }
    last_presence_detected = None
    
    print(f"\t\tTemp controlled rooms {temp_controlled_rooms}.")

    # Populate pump / cycle vars
    last_issued_pump_command = {}
    cycle_master_overrides = {}
    for cycle in range(1, 5):
        last_issued_pump_command[cycle] = None
        cycle_master_overrides[cycle] = int(config_data[f'cycle_{cycle}_master_override'])

    # Set other vars
    external_temp_allow = None
    day_names = {1: 'Hétfő', 2: 'Kedd', 3: 'Szerda', 4: 'Csütörtök', 5: 'Péntek', 6: 'Szombat', 7: 'Vasárnap'}
    last_known_external_temp = (None, None)

    if verbose == 0:
        print("\t\tVerbose mode OFF, shutting up.")
    else:
        report("\t\tVerbose mode ON.")


def refresh_config_from_user():
    try:
        # Copy from user editable version to safe version
        shutil.copy(data_and_config_folder + '/config_user.csv', data_and_config_folder + '/config_safe.csv')

        # Refresh the config using the safe version
        load_config_from_local()
        report("\tConfiguration updated successfully from online config.")

    except Exception as e:
        # If there's any issue, skip the update but log/report the error
        report(f"\tCouldn't update configuration from online config due to: {e}")


def load_sensor_mappings():
    global temp_sensor_to_room, hum_sensor_to_room, room_to_temp_sensor, room_to_hum_sensor, used_temperature_sensor_ids

    temp_sensor_to_room = {}
    hum_sensor_to_room = {}
    room_to_temp_sensor = {}
    room_to_hum_sensor = {}
    used_temperature_sensor_ids = []

    with open(data_and_config_folder + '/sensor_info.csv', 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            room = int(row['room'])
            temp_sensor_num = int(row['temp'])
            used_temperature_sensor_ids.append(int(row['temp']))
            hum_sensor_num = int(row['hum'])

            temp_sensor_to_room[temp_sensor_num] = room
            hum_sensor_to_room[hum_sensor_num] = room

            room_to_temp_sensor[room] = temp_sensor_num
            room_to_hum_sensor[room] = hum_sensor_num
    print("Sensor mappings loaded:")
    print(temp_sensor_to_room)
    print(hum_sensor_to_room)
    print(room_to_temp_sensor)
    print(room_to_hum_sensor)


def load_plug_mappings():
    global room_to_plug, plug_to_id, plug_to_ip, plug_to_key

    room_to_plug = {}
    plug_to_id = {}
    plug_to_ip = {}
    plug_to_key = {}

    with open(data_and_config_folder + '/plug_info.csv', 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            room = int(row['room'])
            plug_num = int(row['num'])

            # Since a room is associated with one plug, we use direct assignment
            room_to_plug[room] = plug_num
            plug_to_id[plug_num] = str(row['id'])
            plug_to_ip[plug_num] = str(row['ip'])
            plug_to_key[plug_num] = str(row['key'])

    print("Plug mappings loaded:")
    print(room_to_plug)
    print(plug_to_id)
    print(plug_to_ip)
    print(plug_to_key)


def pump_startup():
    global pump_status

    current_pump_status = {}
    for pump in range(1,5):
        current_pump_status[pump] =  1 if get_plug_status(plug_to_id[pump], plug_to_ip[pump], plug_to_key[pump]) else 0

    pump_status = current_pump_status
    switch_all_pumps_now(pump_status)
# endregion

# region Command functions
def load_scheduling_commands():
    scheduling_commands = []
    with open(data_and_config_folder + '/scheduling_commands.csv', 'r', encoding='utf-8-sig') as f:
        csv_reader = csv.reader(f)
        for row in csv_reader:
            room_str = row[1]
            for key, value in room_names.items():
                if room_str == value:
                    row[1] = str(key)
                    break

            day_str = row[2]
            for key, value in day_names.items():
                if day_str == value:
                    row[2] = str(key)
                    break

            scheduling_commands.append(row)
    return scheduling_commands


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


def override_commands_housekeeping():
    current_time_values = get_current_time()
    current_time = datetime(current_time_values[0], current_time_values[1], current_time_values[2], current_time_values[3], current_time_values[4])

    valid_commands = []
    expired_commands = []

    # Read the commands and segregate valid and expired commands
    with open(data_and_config_folder + '/override_commands.csv', 'r', encoding='utf-8-sig') as f:
        csv_reader = csv.reader(f)
        for row in csv_reader:
            # Create start_time using start_date and start_hour
            start_time = datetime.strptime(f"{row[2]} {row[3]}", '%d/%m/%Y %H')
            duration = int(row[4])
            end_time = start_time + timedelta(hours=duration)
            if end_time > current_time:
                valid_commands.append(row)
            else:
                expired_commands.append(row)

    # Rewrite the override_commands.csv with only the valid commands
    with open(data_and_config_folder + '/override_commands.csv', 'w', encoding='utf-8-sig', newline='') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerows(valid_commands)

    # Append the expired commands to expired_override_commands.csv
    with open(data_and_config_folder + '/expired_override_commands.csv', 'a', encoding='utf-8-sig', newline='') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerows(expired_commands)
# endregion

# region Helper functions
def unitize(number):
    if number > 0:
        return 1
    elif number < 0:
        return -1
    else:
        return 0


def minutes_since(time_string):
    # Parse the time string into a datetime object
    given_time = datetime.strptime(time_string, "%Y-%m-%dT%H:%M:%S.%f")

    # Get the current local time
    current_time = datetime.now()

    # Calculate the difference in minutes
    time_difference = current_time - given_time
    minutes_passed = time_difference.total_seconds() / 60

    return minutes_passed+60


def get_current_time():
    now = datetime.now()
    return [now.year, now.month, now.day, now.weekday() + 1, now.hour, now.minute]


def download_and_save_csv(url, csv_filename, skip_columns=0, delete_header=True):
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code == 200:
        lines = response.content.decode('utf-8-sig').splitlines()

        # Open the file to write to
        with open(csv_filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)

            # Read the CSV from the URL
            reader = csv.reader(lines)

            for row_number, row in enumerate(reader):
                # Skip the header if delete_header is True
                if row_number == 0 and delete_header:
                    continue

                # Write to local CSV, skipping the specified number of columns
                writer.writerow(row[skip_columns:])
    else:
        report(
            f"Failed to download the CSV. Status code: {response.status_code}")


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


def create_csv_if_not_exists(file_name, header):
    """Creates a CSV file with headers if it doesn't already exist."""
    if not os.path.exists(file_name):
        with open(file_name, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(header)
# endregion

# region Scheduling functions
def load_schedules():
    schedules = {}

    # Generate the list of filenames based on room_names values
    schedule_files = [
        os.path.join(data_and_config_folder, f'schedule_{room_name}.csv')
        for room_name in room_names.values()
    ]

    for schedule_file in schedule_files:
        room_name = os.path.basename(schedule_file).split('_')[1].replace('.csv', '')
        schedule_array = load_csv_file(schedule_file)

        # Assuming you want to map room numbers to their schedules
        for key, value in room_names.items():
            if room_name == value:
                schedules[key] = schedule_array

    return schedules
# endregion

# region IO
async def read_sensors_async():
    # Run with asyncio.run(read_sensors_async())
    host = '192.168.34.106'
    port = '80'
    api_key = '78F42741A3'  # Előbb get_api_key kell fusson, hogy ez meglegyen.
    
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, host, port, api_key)
        await deconz.refresh_state()

    sensor_ids = []
    sensor_raw_list = []
    presence = -1
    for sensor_id, sensor in deconz.sensors.items():
        if int(sensor_id) in used_temperature_sensor_ids:
            try:
                sensor_ids.append(int(sensor_id))
                sensor_raw_list.append(sensor.raw)
            except Exception as e:
                report(f"Error processing sensor {sensor_id}: {e}")

        if sensor.name == 'Oktopusz_jelenlet':
            try:
                presence = sensor.presence
            except Exception as e:
                report(f"Couldn't read presence sensor due to {e}")
    
    last_updated_list = []
    reachable_list = []
    temperatures_list = []
    for raw in sensor_raw_list:
        last_updated_list.append(datetime.strptime(raw['state']['lastupdated'], '%Y-%m-%dT%H:%M:%S.%f')+timedelta(hours=1))
        reachable_list.append(raw['config']['reachable'])
        if raw['type'] == 'ZHATemperature':
            temperatures_list.append(raw['state']['temperature']/100)

    last_updated_by_sensor_id = dict(zip(sensor_ids,last_updated_list))
    reachable_by_sensor_id = dict(zip(sensor_ids,reachable_list))
    temperatures_by_sensor_id = dict(zip(sensor_ids,temperatures_list))

    return last_updated_by_sensor_id, reachable_by_sensor_id, temperatures_by_sensor_id, presence

def deconz_disconnect():
    global deconz_disconnect_threshold, startup_time
    if 3*60 < time.time() - startup_time:
        last_updated_list, _, _, _ = asyncio.run(read_sensors_async())
        mins_since_last_update = (datetime.now() - max(last_updated_list.values())).total_seconds()/60
        if deconz_disconnect_threshold < mins_since_last_update:
            report(f"Deconz disconnect detected (last update {round(mins_since_last_update)} mins ago).")
            return True
        else:
            return False
    else:
        return False

def read_presence_sensor():
    global last_presence_detected
    _, _, _, presence = asyncio.run(read_sensors_async())
    log({
        '1': 'event',
        '2': 'presence',
        '3': presence
        })
    if presence == True:
        report("\tPresence detected at Oktopusz 1.")
    elif presence == False:
        report("\tNo presence detected at Oktopusz 1.")
    else:
        report("\tCouldn't read presence sensor in Oktopusz 1.")

    return presence

def read_temp_sensors():
    global controlled_rooms,temp_controlled_rooms
    last_updated_by_sensor_id, reachable_by_sensor_id, temperatures_by_sensor_id, _ = asyncio.run(read_sensors_async())

    last_updated_by_room = {}
    reachable_by_room = {}
    temperatures_by_room = {}
    for room in temp_controlled_rooms:
        last_updated_by_room[room] = last_updated_by_sensor_id[room_to_temp_sensor[room]]
        reachable_by_room[room] = reachable_by_sensor_id[room_to_temp_sensor[room]]
        temperatures_by_room[room] = temperatures_by_sensor_id[room_to_temp_sensor[room]]
    
    return last_updated_by_room, reachable_by_room, temperatures_by_room

def pump_commands_housekeeping():
    # Read in the whole of pump_commands.csv
    with open(data_and_config_folder + '/pump_commands.csv', 'r') as f:
        reader = csv.DictReader(f)
        commands = [row for row in reader]

    # Get current timestamp
    now = datetime.now()

    # Initialize empty dictionaries
    future_commands = {}
    latest_commands = {}
    expired_commands = {}

    for row in commands:
        command_time = datetime.strptime(row['time'], '%Y-%m-%d-%H-%M-%S')
        pump_num = int(row['pump'])

        if command_time > now:  # Group 1: commands that are in the future
            if pump_num not in future_commands:
                future_commands[pump_num] = []
            future_commands[pump_num].append(row)

        else:
            if pump_num not in latest_commands or datetime.strptime(latest_commands[pump_num]['time'], '%Y-%m-%d-%H-%M-%S') < command_time:
                # If this command is more recent than current latest command
                if pump_num in latest_commands:
                    if pump_num not in expired_commands:
                        expired_commands[pump_num] = []
                    expired_commands[pump_num].append(
                        latest_commands[pump_num])
                # Group 2: latest command that is not in the future
                latest_commands[pump_num] = row
            else:
                if pump_num not in expired_commands:
                    expired_commands[pump_num] = []
                # Group 3: commands that are before the latest one
                expired_commands[pump_num].append(row)

    # Recreate pump_commands.csv with only Group 1 and 2
    with open(data_and_config_folder + '/pump_commands.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['time', 'pump', 'command'])  # Writing the headers
        for _, v in latest_commands.items():
            writer.writerow([v['time'], v['pump'], v['command']])
        for pump_num, command_list in future_commands.items():
            for command in command_list:
                writer.writerow([command['time'], command['pump'], command['command']])

    # Create expired_pump_commands.csv if it does not exist
    create_csv_if_not_exists(
        data_and_config_folder + '/expired_pump_commands.csv', ['time', 'pump', 'command'])

    # Append Group 3 to expired_pump_commands.csv
    with open(data_and_config_folder + '/expired_pump_commands.csv', 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        for pump_num, command_list in expired_commands.items():
            for command in command_list:
                writer.writerow([command['time'], command['pump'], command['command']])


def issue_pump_command(pump, command, lag=0):
    """Issues a command for a pump and appends it to the pump_commands.csv file."""
    file_name = data_and_config_folder + "/pump_commands.csv"

    # Adjust the current time by the given lag
    adjusted_time = datetime.now() + timedelta(seconds=lag)

    # Format timestamp as desired
    timestamp = adjusted_time.strftime('%Y-%m-%d-%H-%M-%S')

    create_csv_if_not_exists(file_name, ["time", "pump", "command"])

    with open(file_name, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([timestamp, pump, command])

    log({
        '1': 'event',
        '2': 'pump command issue',
        '3': {pump: command, 'lag': lag}
    })
    report(f"\t\tPump {pump} is to be turned {['OFF','ON'][command]} in {[pump_off_lag,pump_on_lag][command]} seconds.")


def read_pump_setting():
    file_name = data_and_config_folder + "/pump_commands.csv"
    latest_commands = {}

    # Ensure file exists
    if not os.path.exists(file_name):
        return {1: 0, 2: 0, 3: 0, 4: 0}

    with open(file_name, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            command_time = datetime.strptime(row['time'], '%Y-%m-%d-%H-%M-%S')
            current_time = datetime.now()

            if command_time <= current_time:
                pump_num = int(row['pump'])
                if pump_num not in latest_commands or command_time > datetime.strptime(latest_commands[pump_num]['time'], '%Y-%m-%d-%H-%M-%S'):
                    latest_commands[pump_num] = row

    # Create a pump setting dictionary
    pump_setting = {}
    for i in range(1, 5):
        if i in latest_commands:
            pump_setting[i] = int(latest_commands[i]['command'])
        else:
            pump_setting[i] = 0

    return pump_setting

def get_plug_status(id, ip, key):
    plug = tinytuya.OutletDevice(
        dev_id=id,
        address=ip,
        local_key=key,
        version=3.3)

    status = (plug.status())['dps']['1']

    return status

def switch_plug(id, ip, key, setting):
    plug = tinytuya.OutletDevice(
        dev_id=id,
        address=ip,
        local_key=key,
        version=3.3)

    status = (plug.status())['dps']['1']

    if setting == 1 and status == 0:
        return (plug.turn_on())['dps']['1']
    elif setting == 0 and status == 1:
        return (plug.turn_off())['dps']['1']
    else:
        return status

def issue_albatros_command(command, lag=0):
    file_name = data_and_config_folder + "/albatros_commands.csv"

    # Adjust the current time by the given lag
    adjusted_time = datetime.now() + timedelta(seconds=lag)

    # Format timestamp as desired
    timestamp = adjusted_time.strftime('%Y-%m-%d-%H-%M-%S')

    create_csv_if_not_exists(file_name, ["time", "command"])

    with open(file_name, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([timestamp, command])

    log({
        '1': 'event',
        '2': 'albatros command issue',
        '3': command
    })


def read_albatros_setting():
    file_name = data_and_config_folder + "/albatros_commands.csv"

    # Default setting is 0, change as per your system's default state
    latest_command = 0
    latest_command_time = None

    # Ensure file exists, otherwise return the default setting
    if not os.path.exists(file_name):
        return latest_command

    with open(file_name, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            command_time = datetime.strptime(row['time'], '%Y-%m-%d-%H-%M-%S')
            current_time = datetime.now()

            # If the command is in the past and it's either the first command or newer than the previous one
            if command_time <= current_time and (not latest_command_time or command_time > latest_command_time):
                latest_command = int(row['command'])
                latest_command_time = command_time

    # Return the latest valid command
    return latest_command


def albatros_commands_housekeeping():
    pass


def update_external_temperature(last_known_data):
    global external_temp_validity_threshold

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 47.4984,
        "longitude": 19.0405,
        "current_weather": "true"
    }

    try:
        response = requests.get(url, params=params)
        # This will raise an HTTPError if the status is 4xx or 5xx
        response.raise_for_status()

        data = response.json()
        temperature = data['current_weather']['temperature']
        # Get the current timestamp in ISO format
        timestamp = datetime.utcnow().isoformat()

        return (timestamp, temperature)

    except Exception as e:
        # report the error
        report(f"\tError occurred during external temperature scraping: {e}")

        # Check if last known data exists and has a timestamp
        if last_known_data[0]:
            last_known_timestamp = datetime.fromisoformat(last_known_data[0])
            current_timestamp = datetime.utcnow()

            log({
                '1': 'event',
                '2': 'external temp update',
                '3': {'success': 0, 'details': get_exception_details(e)}
            })

            # Check if the last known timestamp is older than the max_age_seconds
            if (current_timestamp - last_known_timestamp) > timedelta(seconds=external_temp_validity_threshold):
                return (None, None)  # If too old, return (None, None)

    # Return the last known data if an error occurred and it's not too old
    return last_known_data
# endregion

# region Logging and pushing
if not test:
    logger = logging.getLogger('log')
    logger.setLevel(logging.INFO)

    handler = TimedRotatingFileHandler('logs/log', when='midnight', interval=1, backupCount=1000, encoding='utf-8')
    logger.addHandler(handler)

def report(message):
    if verbose == 1:
        print(message)
        if not test:
            send_to_firebase('console','message',message)

def log(entry):
    entry['4'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    json_entry = json.dumps(entry)
    logger.info('%s', json_entry)


def get_exception_details(e):
    error_message = str(e)
    _, _, tb = sys.exc_info()
    tb_info = traceback.extract_tb(tb)
    # If the traceback is available, get the last call
    if tb_info:
        filename, line, func, text = tb_info[-1]
    else:
        filename, line, func, text = (None, None, None, None)
    return {
        'error_message': error_message,
        'filename': filename,
        'line': line,
        'function': func,
        'text': text
    }

def push_to_repo(commit_message, to_add):
    report(f"Start push to repo: {commit_message}.")
    try:
        subprocess.check_call(["git", "pull"])
        for item in to_add:
            subprocess.check_call(["git", "add", item])
        subprocess.check_call(["git", "commit", "-m", commit_message])
        subprocess.check_call(["git", "push"])
        report(f"\tOperation {commit_message} completed successfully.")

    except subprocess.CalledProcessError as e:
        report(f"\tAn error occurred during git operations: {e}. Return code: {e.returncode}, Output: {e.output}")
        log({
            '1': 'error',
            '2': commit_message,
            '3': {'details':get_exception_details(e)}
        })

    except Exception as e:
        report(f"Unexpected error: {sys.exc_info()[0]} during {commit_message}.")
        log({
            '1': 'error',
            '2': commit_message,
            '3': {'details':get_exception_details(e)}
        })
    
    report(f"Push to repo: {commit_message} finished.\n")

# endregion


# region Firebase
if not test:
    global fb_cred
    fb_cred = credentials.Certificate('firebase_creds.json')

    firebase_admin.initialize_app(fb_cred, {
        'databaseURL': 'https://kazankontroll-database-default-rtdb.europe-west1.firebasedatabase.app'
    })

def firebase_update_detected(event):
    report('Firebase update at path: {}, data: {}'.format(event.path, event.data))

    update_needed = [False, False, False]

    if 'config' in event.data and last_config_update < datetime.strptime(event.data['config']['timestamp'],"%Y.%m.%d. %H:%M:%S"):
        update_needed[0] = True
    if 'override' in event.data and last_override_update < datetime.strptime(event.data['override']['timestamp'],"%Y.%m.%d. %H:%M:%S"):
        update_needed[1] = True
    if 'schedule' in event.data and last_schedules_update < datetime.strptime(event.data['schedule']['timestamp'],"%Y.%m.%d. %H:%M:%S"):
        update_needed[2] = True

    if True in update_needed:
        refresh_and_update('firebase update', config_update=update_needed[0], override_update=update_needed[1], schedule_update=update_needed[2])

if not test:
    global firebase_listener
    firebase_listener = db.reference('updates/').listen(firebase_update_detected)

    firebase_sent = {}

def send_to_firebase(path, key, value, trials = 0):
    try:
        firebase_sent[f'{path}/{key}'] = value
        ref = db.reference(path)
        ref.update({key: value})
    except Exception as e:
        if trials < 10:
            report(f"Couldn't send to firebase due to {e}, trying again in 1 s for the {trials}-th time.")
            time.sleep(1)
            send_to_firebase(path, key, value, trials = trials+1)
        else:
            report(f"Couldn't send to firebase due to {e} 10 times, not trying again.")
# endregion

# region Control
def determine_set_temps_for_room():
    global controlled_rooms, room_names, temp_controlled_rooms

    schedules = load_schedules()
    override_commands = load_override_commands()

    current_time_values = get_current_time()
    current_time = datetime(current_time_values[0], current_time_values[1], current_time_values[2], current_time_values[4], current_time_values[5])

    set_temps = {}
    for room in controlled_rooms:
        if room in schedules:
            schedule = schedules[room]
            current_row = current_time.hour
            # Python's weekday() is already 0-indexed (Monday = 0)
            current_day = current_time.weekday()
            set_temps[room] = schedule[current_row][current_day]

            # Override logic: Check if there is a valid override command for the current room and time
            latest_cmd_time = datetime.min
            latest_temp = None
            # Track if a newer clear command has been found after a temp command
            clear_override_after_temp = False

            for cmd in override_commands:
                cmd_issue_time = datetime.strptime(cmd[0], '%d/%m/%Y %H:%M:%S')
                cmd_start_time = datetime.strptime(f"{cmd[2]} {cmd[3]}", '%d/%m/%Y %H')
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
                set_temps[room] = latest_temp
                overrides[room] = 1
                report("\tActive override found for " + room_names[room])
                log({
                    '1': 'state',
                    '2': 'override detection',
                    '3': room
                })
            else:
                overrides[room] = 0
    return set_temps


def refresh_and_update(reason, config_update=False, override_update=False, schedule_update=False):
    global room_names, room_gids
    global latest_config_got, latest_override_got, latest_schedules_got
    global last_config_update, last_override_update, last_schedules_update
    report(f"Start refresh and update due to {reason}.")
    if config_update:
        try:
            download_and_save_csv(
                'https://docs.google.com/spreadsheets/d/e/2PACX-1vSEiiNYdSFXxQInKCrERcHkEKH-MVJuglz2XHnUhEZvR4SBcrw85MU5X-ioQFmaF25lMGJZWkXSfWN5/pub?output=csv',
                data_and_config_folder + '/config_user.csv',
                skip_columns=0,
                delete_header=False
            )
            log({
                '1': 'event',
                '2': 'config update',
                '3': {'success': 1}
            })
            report("\tSuccessfully downloaded config csv.")
            latest_config_got = True
            last_config_update = datetime.now()
            refresh_config_from_user()
        except Exception as e:
            report("\tCouldn't download config csv.")
            latest_config_got = False
            log({
                '1': 'event',
                '2': 'config update',
                '3': {'success': 0, 'details': get_exception_details(e)}
            })

    if override_update:
        try:
            download_and_save_csv(
                'https://docs.google.com/spreadsheets/d/e/2PACX-1vTiSvyjKOJk9UdY2OZQLpAfvJiEE2fkH9rc03AEzoqyUcOG1N7Kr_KOtABKeUpLxy3KzcvWjeBcTQ_P/pub?output=csv',
                data_and_config_folder + '/override_commands.csv',
                skip_columns=0,
                delete_header=True
            )
            log({
                '1': 'event',
                '2': 'override update',
                '3': {'success': 1}
            })
            report("\tSuccessfully downloaded override csv.")
            latest_override_got = True
            last_override_update = datetime.now()
        except Exception as e:
            report("\tCouldn't download override csv.")
            log({
                '1': 'event',
                '2': 'override update',
                '3': {'success': 0, 'details': get_exception_details(e)}
            })
            latest_override_got = False

    if schedule_update:
        try:
            for room in controlled_rooms:
                download_and_save_csv(
                    f'https://docs.google.com/spreadsheets/d/e/2PACX-1vSK3qSnFPxW2SLWPfD7w0qnGfq2aI_YdctT9arkHgucYWvUzO5FrsVCbJHOOusL1YPrvdQWNnYwz59r/pub?output=csv&gid={room_gids[room]}',
                    f'{data_and_config_folder}/schedule_{room_names[room]}.csv',
                    skip_columns=1,
                    delete_header=True
                )
            log({
                '1': 'event',
                '2': 'schedule update',
                '3': {'success': 1}
            })
            report("\tSuccessfully downloaded schedule csvs.")
            latest_schedules_got = True
            last_schedules_update = datetime.now()
        except Exception as e:
            report("\tCouldn't download schedule csvs.")
            log({
                '1': 'event',
                '2': 'schedule update',
                '3': {'success': 0, 'details': get_exception_details(e)}
            })
            latest_schedules_got = False

    report("End refresh and update.\n")


def compare_and_command():
    report("Start compare and command.")
    current_time_values = get_current_time()
    current_time = datetime(current_time_values[0], current_time_values[1], current_time_values[2], current_time_values[4], current_time_values[5])
    report("\tCurrent time: {:02}:{:02}".format(current_time.hour, current_time.minute))
    global set_temps, measured_temps, overrides
    global last_update_from_room, sensor_reachable_in_room 
    global controlled_rooms,temp_controlled_rooms
    global last_presence_detected, no_presence_min_temp

    prev_last_update_from_room = last_update_from_room
    prev_sensor_reachable_in_room = sensor_reachable_in_room
    prev_measured_temps = measured_temps

    last_update_from_room, sensor_reachable_in_room, measured_temps = read_temp_sensors()
    measured_temps[8] = 0.5 # Trafóház

    for room in temp_controlled_rooms:
        if f'systemState/roomStatuses/{room}' not in firebase_sent or firebase_sent[f'systemState/roomStatuses/{room}'] != measured_temps[room]:
            send_to_firebase('systemState/roomStatuses', room, measured_temps[room])
        if prev_measured_temps[room] != measured_temps[room]:
            log({
                '1': 'state',
                '2': 'temp measurement',
                '3': {room: measured_temps[room]}
            })
        
        if f'systemState/roomReachable/{room}' not in firebase_sent or firebase_sent[f'systemState/roomReachable/{room}'] != sensor_reachable_in_room[room]:
            send_to_firebase('systemState/roomReachable', room, sensor_reachable_in_room[room])
        if prev_sensor_reachable_in_room[room] != sensor_reachable_in_room[room]:
            log({
                '1': 'state',
                '2': 'room reachability',
                '3': {room: sensor_reachable_in_room[room]}
            })

        if f'systemState/roomLastUpdate/{room}' not in firebase_sent or firebase_sent[f'systemState/roomLastUpdate/{room}'] != last_update_from_room[room].strftime('%m.%d. %H:%M'):
            send_to_firebase('systemState/roomLastUpdate', room, last_update_from_room[room].strftime('%m.%d. %H:%M'))
        if prev_last_update_from_room[room] != last_update_from_room[room]:
            log({
                '1': 'state',
                '2': 'room last update',
                '3': {room: last_update_from_room[room].strftime('%m.%d. %H:%M')}
            })

    prev_set_temps = set_temps
    set_temps = determine_set_temps_for_room()

    
    if last_presence_detected != None:
        if 60 > round((datetime.now() - last_presence_detected).total_seconds()/60):
            last_presence_time_string = f"{round((datetime.now() - last_presence_detected).total_seconds()/60)} mins"
        elif datetime.now().day == last_presence_detected.day: 
            last_presence_time_string = f"{round((datetime.now() - last_presence_detected).total_seconds()/3600,1)} hours"
        else:
            last_presence_time_string = f"{round((datetime.now() - last_presence_detected).total_seconds()/86400,1)} days"
        report(f"\tLast presence detected at {last_presence_detected.strftime('%H:%M')} ({last_presence_time_string} ago).")
    
    oktopusz_presence = read_presence_sensor()
    if oktopusz_presence:
        last_presence_detected = datetime.now()
    
    if last_presence_detected == None:
        set_temps[9] = no_presence_min_temp
    elif presence_off_lag < (datetime.now() - last_presence_detected).total_seconds()/60:
        set_temps[9] = no_presence_min_temp
    elif oktopusz_presence == -1: # Bearable temp set for invalid sensor reading
        set_temps[9] = 16

    for room in temp_controlled_rooms:
        if f'systemState/roomSettings/{room}' not in firebase_sent or firebase_sent[f'systemState/roomSettings/{room}'] != set_temps[room]:
            send_to_firebase('systemState/roomSettings', room, set_temps[room])
        if prev_set_temps[room] != set_temps[room]:
            log({
                '1': 'state',
                '2': 'set temp',
                '3': {room: set_temps[room], "buff low":hysteresis_buffers[room]["lower"], "buff high":hysteresis_buffers[room]["upper"]}
            })

    global albatros_status
    global last_known_external_temp

    prev_last_known_external_temp = last_known_external_temp[1]
    last_known_external_temp = update_external_temperature(last_known_external_temp)
    if last_known_external_temp[1] != prev_last_known_external_temp:
        log({
            '1': 'state',
            '2': 'external temp',
            '3': last_known_external_temp[1]
        })

    global external_temp_allow, last_update_from_room_tolerance
    global last_issued_pump_command
    prev_external_temp_allow = external_temp_allow

    pump_votes = {1: 0, 2: 0, 3: 0, 4: 0}
    albatros_vote = 0

    try:
        if last_known_external_temp[1] == None or last_known_external_temp[1] < external_temp_threshold:
            report(f"\tExternal temp ({last_known_external_temp[1]} °C) is below threshold ({external_temp_threshold} °C), continuing with room comparisons.")
            if f'systemState/externalTempAllow' not in firebase_sent or firebase_sent['systemState/externalTempAllow'] != 1:
                send_to_firebase('systemState', 'externalTempAllow', 1)
            for room in temp_controlled_rooms:
                minutes_since_last_update = round((datetime.now() - last_update_from_room[room]).total_seconds() / 60)
                lower_buffer = set_temps[room] - hysteresis_buffers[room]["lower"]
                upper_buffer = set_temps[room] + hysteresis_buffers[room]["upper"]
                report(f"\t\t{room_names[room]}: {measured_temps[room]} °C ({minutes_since_last_update} mins ago), set: {lower_buffer}-{set_temps[room]}-{upper_buffer}.")

                pump = room_to_plug[room]
                vote = -1
                reason = 'none given'
                if cycle_master_overrides[pump] == 0:
                    if measured_temps[room] < lower_buffer:
                        vote = 1
                        reason = 'LOW'
                    elif measured_temps[room] > upper_buffer:
                        vote = 0
                        reason = 'HIGH'
                    else:
                        vote = pump_status[pump]
                        reason = ["OFF","ON"][pump_status[pump]]+" hysteresis"
                elif cycle_master_overrides[pump] == 1:
                    vote = 1
                    reason = "master ON"
                else:
                    vote = 0
                    reason = "master OFF"

                if not sensor_reachable_in_room[room]:
                    report(f"\t\t\tWarning: sensor is unreachable!")

                # ZigBee mesh breakdown logic
                if pump_status[pump] != 1 and 0 < unitize(set_temps[room]) and measured_temps[7] < kisterem_tolerance and (last_update_from_room_tolerance < minutes_since_last_update or sensor_reachable_in_room[room] == False):
                    report(f"\t\tKisterem override, {room_names[room]}, had no update for {minutes_since_last_update} minutes.")
                    log({
                        '1': 'decision',
                        '2': 'kisterem override',
                        '3': room
                    })
                    if f'decisions/kisteremOverride/{room}' not in firebase_sent or firebase_sent[f'decisions/kisteremOverride/{room}']['override'] != 1:
                        send_to_firebase(f'decisions/kisteremOverride',room,{'override':1,'timestamp':datetime.now().strftime('%m.%d. %H:%M')})
                    overrides[room] = 1
                    vote = 1
                    reason = 'kisterem override'
                elif f'decisions/kisteremOverride/{room}' not in firebase_sent or firebase_sent[f'decisions/kisteremOverride/{room}']['override'] != 0:           
                        send_to_firebase(f'decisions/kisteremOverride',room,{'override':0,'timestamp':datetime.now().strftime('%m.%d. %H:%M')})
                
                if vote != -1:
                    report(f"\t\t\t{room_names[room]} voting {vote} on cycle {pump} (reason: {reason}).")
                    pump_votes[pump] += vote
                    albatros_vote += vote
                    #report(f"\t\t\tPump votes: {pump_votes}, albatros vote: {albatros_vote}.")
                else:
                    report(f"\t\t{room_names[room]}: voting issue.")
                    raise Exception(f"Voting issue with {room_names[room]}.")

        else:
            report(f"\tExternal temp ({last_known_external_temp[1]} °C) is above threshold ({external_temp_threshold} °C).")
            if f'systemState/externalTempAllow' not in firebase_sent or firebase_sent['systemState/externalTempAllow'] != 0:
                send_to_firebase('systemState', 'externalTempAllow', 0)

        if external_temp_allow != prev_external_temp_allow:
            log({
                '1': 'decision',
                '2': 'external temp',
                '3': external_temp_allow
            })
            send_to_firebase('decisions', 'externalTempAllow', {'decision': external_temp_allow, 'reason': ['above', 'below'][external_temp_allow], 'timestamp': datetime.now().strftime('%m.%d. %H:%M')})

        report(f"\tSummed pump votes: {pump_votes}, albatros vote: {albatros_vote}.")
        report(f"\tPump status: {pump_status}, albatros status: {albatros_status}.")
        for pump, vote in pump_votes.items():
            if last_issued_pump_command[pump] != unitize(vote):
                log({
                    '1': 'decision',
                    '2': 'cycle',
                    '3': {pump: vote}
                })
                send_to_firebase('decisions/cycle', pump, {'decision': vote, 'reason': 'vote', 'timestamp': datetime.now().strftime('%m.%d. %H:%M')})
            
        if albatros_status != unitize(albatros_vote):
            log({
                '1': 'decision',
                '2': 'heating',
                '3': albatros_vote
            })
            send_to_firebase('decisions', 'albatros', {'decision': albatros_vote, 'reason': 'vote', 'timestamp': datetime.now().strftime('%m.%d. %H:%M')})
        elif albatros_status == 1 and albatros_vote == 1 and firebase_sent['decisions/albatros']['reason'] == 'zigbee mesh override':
            send_to_firebase('decisions', 'albatros', {'decision': albatros_vote, 'reason': 'vote', 'timestamp': datetime.now().strftime('%m.%d. %H:%M')})
        
        for pump, vote in pump_votes.items():
            if unitize(vote) != last_issued_pump_command[pump]:
                report(f"\tIssuing {['OFF','ON'][unitize(vote)]} command for pump {pump}.")
                issue_pump_command(pump, unitize(vote), [pump_off_lag,pump_on_lag][unitize(vote)])
                last_issued_pump_command[pump] = unitize(vote)

        if unitize(albatros_vote) != albatros_status:
            report(f"\tIssuing {['OFF','ON'][unitize(albatros_vote)]} command for albatros.")
            issue_albatros_command(unitize(albatros_vote), 0)

    except Exception as e:
        report(f"Couldn't finish compare and command due to: {e}")

    report("End compare and command.\n")


def control_pumps():
    report("Start pump control.")
    global pump_status

    pump_commands_housekeeping()

    pump_setting = read_pump_setting()
    report("\t"+f"Current pump setting: {pump_setting}")
    report("\t"+f"Current pump status: {pump_status}")

    for pump, setting in pump_setting.items():
        if pump_status[pump] != setting:
            # Turn on pump
            if setting == 1 and pump_status[pump] == 0:
                log({
                    '1': 'decision',
                    '2': 'pump switch',
                    '3': {pump: 1}
                })
                report("\t"+f"Turning ON Pump {pump}...")
                if switch_plug(plug_to_id[pump], plug_to_ip[pump], plug_to_key[pump], setting):
                    pump_status[pump] = 1
                    report("\t\t"+f"Pump {pump} is ON")
                    send_to_firebase('systemState/pumpStatuses', pump, 1)
                    log({
                        '1': 'state',
                        '2': 'pump',
                        '3': {pump: 1}
                    })
                else:
                    report("\t\t"+f"Pump {pump} could not be turned ON.")
                    log({
                        '1': 'error',
                        '2': 'pump error',
                        '3': {pump: 1}
                    })
            # Turn off pump
            elif setting == 0 and pump_status[pump] == 1:
                log({
                    '1': 'decision',
                    '2': 'pump switch',
                    '3': {pump: 0}
                })
                report(f"Turning OFF Pump {pump}...")
                if not switch_plug(plug_to_id[pump], plug_to_ip[pump], plug_to_key[pump], setting):
                    pump_status[pump] = 0
                    report("\t\t"+f"Pump {pump} is OFF")
                    send_to_firebase('systemState/pumpStatuses', pump, 0)
                    log({
                        '1': 'state',
                        '2': 'pump',
                        '3': {pump: 0}
                    })
                else:
                    report("\t\t"+f"Pump {pump} could not be turned OFF.")
                    log({
                        '1': 'error',
                        '2': 'pump error',
                        '3': {pump: 0}
                    })
            elif pump_status[pump] == -1:
                report("\t\t"+f"Pump {pump} is not controlled in this session.")
    report("End pump control.\n")


def control_albatros():
    global albatros_status, GPIOpin
    report("Start albatros control.")
    albatros_setting = read_albatros_setting()
    if albatros_setting != albatros_status:
        if albatros_setting == 0 and albatros_status == 1:
            log({
                '1': 'decision',
                '2': 'albatros switch',
                '3': 0
            })
            report("\tTurning albatros OFF.")
            GPIO.output(GPIOpin, GPIO.LOW)
            albatros_status = 0
            send_to_firebase('systemState', 'albatrosStatus', 0)
            log({
                '1': 'state',
                '2': 'albatros',
                '3': 0
            })
        elif albatros_setting == 1 and albatros_status == 0:
            log({
                '1': 'decision',
                '2': 'albatros switch',
                '3': 1
            })
            report("\tTurning albatros ON.")
            GPIO.output(GPIOpin, GPIO.HIGH)
            albatros_status = 1
            send_to_firebase('systemState', 'albatrosStatus', 1)
            log({
                '1': 'state',
                '2': 'albatros',
                '3': 1
            })
    else:
        report(f"\tAlbatros status {albatros_status} matches setting {albatros_setting}.")
    report("End albatros control.\n")
# endregion

# region Error handling & RasPi monitoring
def switch_all_pumps_now(direct_pump_setting):
    log({
        '1': 'decision',
        '2': 'pump switch',
        '3': direct_pump_setting
    })

    for pump, setting in direct_pump_setting.items():
        if setting == 1:
            if switch_plug(plug_to_id[pump], plug_to_ip[pump], plug_to_key[pump], setting):
                report("\t\t"+f"Pump {pump} is ON")
                #send_to_firebase('systemState/pumpStatuses', pump, 1)
                log({
                    '1': 'state',
                    '2': 'pump',
                    '3': {pump: 1}
                })
            else:
                report("\t\t"+f"Pump {pump} could not be turned ON.")
                log({
                    '1': 'error',
                    '2': 'pump',
                    '3': {pump: 1}
                })
        elif setting == 0:
            if switch_plug(plug_to_id[pump], plug_to_ip[pump], plug_to_key[pump], setting) == 0:
                report("\t\t"+f"Pump {pump} is OFF")
                #send_to_firebase('systemState/pumpStatuses', pump, 0)
                log({
                    '1': 'state',
                    '2': 'pump',
                    '3': {pump: 0}
                })
            else:
                report("\t\t"+f"Pump {pump} could not be turned OFF.")
                log({
                    '1': 'error',
                    '2': 'pump',
                    '3': {pump: 0}
                })

def switch_albatros_now(status):
    global GPIOpin
    GPIO.setup(GPIOpin, GPIO.OUT)
    log({
        '1': 'decision',
        '2': 'albatros',
        '3': status
    })
    if status == 1:
        GPIO.output(GPIOpin, GPIO.HIGH)
        report(f"GPIO pin: {GPIOpin} set to HIGH, albatros should be ON.")
        log({
            '1': 'state',
            '2': 'albatros',
            '3': 1
        })
    elif status == 0:
        GPIO.output(GPIOpin, GPIO.LOW)
        report(f"GPIO pin: {GPIOpin} set to LOW, albatros should be OFF.")
        log({
            '1': 'state',
            '2': 'albatros',
            '3': 0
        })
    else:
        report("Bad albatros command.")

def send_email(subject, message):
    sender_email = "kazankontroll@gmail.com"
    receiver_email = "markus.benjamin@gmail.com"
    password = "ytjd xnnq lmci jrop"
    email = MIMEMultipart()
    email["From"] = sender_email
    email["To"] = receiver_email
    email["Subject"] = subject
    email.attach(MIMEText(message, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, email.as_string())

def get_CPU_temperature():
    output = subprocess.run(['vcgencmd', 'measure_temp'],capture_output=True, text=True).stdout
    temp_str = output.split('=')[1].split('\'')[0]
    return float(temp_str)

def monitor_CPU_temp():
    current_CPU_temp = get_CPU_temperature()
    report(f"Current CPU temp: {current_CPU_temp} °C")

    if CPU_temp_logging < current_CPU_temp:
        log({
            '1': 'state',
            '2': 'RasPi',
            '3': {'CPU temp': current_CPU_temp}
        })

    if CPU_temp_warning < current_CPU_temp:
        send_email("RasPi overheat warning", f"CPU temp: {get_CPU_temperature()}")

def error_notification(error_message, send_email_alert, exception=None): #Generic notification routine in case of unexpected errors
    report(error_message)
    if exception != None:
        log({
            '1': 'error',
            '2': 'RasPi',
            '3': {'message': error_message, 'details': get_exception_details(exception)}
        })
    else:
        log({
            '1': 'error',
            '2': 'RasPi',
            '3': {'message': error_message}
        })

    try:
        if send_email_alert:
            if exception is not None:
                send_email("Control error", "")
            else:
                send_email("Control error", get_exception_details(exception))
    except Exception as e:
        send_email("Control error", "")
        report(f"Even error routine could not be executed due to: {e}.")

def error_handling(): #Specific handling routine in case of known errors
    global run
    if deconz_disconnect():
        if not test:
            send_email("Control error","Deconz disconnect.")
            log({
            '1': 'error',
            '2': 'deconz'
            })
            if isc.connected_to_server:
                report("Requesting reboot from conductor.")
                if not send_message_to_conductor("error:reboot"):
                    report("Couldn't request reboot from conductor (unsuccessful).")
                else:
                    run = False
        else:
            report("Couldn't request reboot from conductor (not connected).")

def shutdown_routine():
    report(f"Control shutdown.")
    if not test:
        send_message_to_conductor("state:stop")
        disconnect_from_conductor()
        log({
            '1': 'event',
            '2': 'shutdown'
        })
        send_to_firebase('systemState','controlStatus',0)
    sys.exit()
# endregion

# region Communicate with conductor & systemd
def sigterm_handler(*args,**kwargs):
    global run
    if run:
        run = False
        report(f"Systemd termination.")

signal.signal(signal.SIGTERM, sigterm_handler) # Register the signal handler for SIGTERM

def connect_to_conductor():
    global run
    if isc.establish_connection_to_server():
        send_message_to_conductor("name:control")
        if run:
            send_message_to_conductor("state:run")
        else: # Unlikely except during startup, but just to make sure
            send_message_to_conductor("state:stop")
        report("Logged in to conductor.")
    else:
        report("Couldn't log in to conductor.")

def disconnect_from_conductor():
    if isc.connected_to_server:
            isc.shutdown_server_connection()

def maintain_conductor_connection():
    """ Connect if not disconnected, receive new messages """
    conductor_connection_test = isc.test_server_connection()
    if conductor_connection_test != None:
        if not conductor_connection_test:
            print("Lost conductor connection.")
            connect_to_conductor()
    else:
        connect_to_conductor()
    
    if isc.connected_to_server:
        isc.receive_message_from_server()

def send_message_to_conductor(message):
    """ Send message, shut down connection if unsuccessful """
    if isc.connected_to_server:
        success = isc.send_message_to_server("control:"+message+";")
        if not success:
            isc.shutdown_server_connection()
        return success

def check_stop_from_conductor():
    if isc.connected_to_server:
        if 0<len(isc.server_messages) and isc.server_messages[-1] == 'stop':
            global run
            run = False
            report(f"Conductor termination.")
# endregion

startup_time = time.time()

def main():
    global test
    try:
        # Startup
        report("Control startup.")
        if test:
            pass
        else:
            global pump_status
            global albatros_status
            global GPIOpin
            global last_known_external_temp
            global last_update_from_room, sensor_reachable_in_room, measured_temps
            global run

            send_email("Control startup.", "")
            log({
                '1': 'event',
                '2': 'startup'
            })

            load_sensor_mappings()
            load_plug_mappings()
            
            pump_startup()
            switch_albatros_now(0)
            albatros_status = 0

            load_config_from_local()
            refresh_and_update("startup", config_update=True, override_update=True, schedule_update=True)

            send_to_firebase('systemState','controlStatus',1)
        
        run = True
        connect_to_conductor()
    except Exception as e:
        report(f"Couldn't start up due to {e}.")
        report(f"Details: {get_exception_details(e)}")
        if not test:
            error_notification(f"Unexpected error during startup: {e}.", True, exception=e)

    # Main control cycle
    while run:
        try:
            if test:
                time.sleep(5) #DEV
                print("Main control cycle.") #DEV
            else:
                maintain_conductor_connection()
                check_stop_from_conductor()
                error_handling()
                current_seconds = int(time.time())
                secs_window = 10
                if current_seconds % (int(repeat_download_retry * 60)) <= secs_window and (not latest_config_got or not latest_override_got or not latest_schedules_got):
                    refresh_and_update('failed download',config_update=not latest_config_got, override_update=not latest_override_got, schedule_update=not latest_schedules_got)
                if current_seconds % (int(repeat_compare_and_command * 60)) <= secs_window:
                    compare_and_command()
                if current_seconds % (int(repeat_control_pumps * 60)) <= secs_window:
                    control_pumps()
                if current_seconds % (int(repeat_control_albatros * 60)) <= secs_window:
                    control_albatros()
                if current_seconds % (int(repeat_monitor_CPU_temp * 60)) <= secs_window:
                    monitor_CPU_temp()
                if current_seconds % (int(repeat_git_log_push * 60)) <= secs_window:
                    push_to_repo('Log and config push', ['logs/log', f'{data_and_config_folder}'])
                # Sleep for a short duration to prevent busy-waiting
                time.sleep(secs_window)
        except KeyboardInterrupt:
            run = False
            report(f"KeyboardInterrupt on main control cycle.")
        except Exception as e:
            if not test:
                error_notification(f"Unexpected error: {e} on main control cycle.", True, exception=e)
            run = False
            report(f"Unexpected error: {e} on main control cycle.")
            report(f"Details: {get_exception_details(e)}")

    else:
        shutdown_routine()

if __name__ == "__main__":
    main()