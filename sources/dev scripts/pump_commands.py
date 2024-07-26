import csv
from datetime import datetime, timedelta
import os
import keyboard

pump_status = {1: 0, 2: 0, 3: 0, 4: 0}

def create_csv_if_not_exists(file_name, header):
    """Creates a CSV file with headers if it doesn't already exist."""
    if not os.path.exists(file_name):
        with open(file_name, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(header)

def pump_commands_housekeeper():
    # Read in the whole of pump_commands.csv
    with open('pump_commands.csv', 'r') as f:
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
                    expired_commands[pump_num].append(latest_commands[pump_num])
                latest_commands[pump_num] = row  # Group 2: latest command that is not in the future
            else:
                if pump_num not in expired_commands:
                    expired_commands[pump_num] = []
                expired_commands[pump_num].append(row)  # Group 3: commands that are before the latest one

    # Recreate pump_commands.csv with only Group 1 and 2
    with open('pump_commands.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['time', 'pump', 'command'])  # Writing the headers
        for _, v in latest_commands.items():
            writer.writerow([v['time'], v['pump'], v['command']])
        for pump_num, command_list in future_commands.items():
            for command in command_list:
                writer.writerow([command['time'], command['pump'], command['command']])

    # Create expired_pump_commands.csv if it does not exist
    create_csv_if_not_exists('expired_pump_commands.csv', ['time', 'pump', 'command'])

    # Append Group 3 to expired_pump_commands.csv
    with open('expired_pump_commands.csv', 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        for pump_num, command_list in expired_commands.items():
            for command in command_list:
                writer.writerow([command['time'], command['pump'], command['command']])

def issue_pump_command(pump, command, lag=0):
    """Issues a command for a pump and appends it to the pump_commands.csv file."""
    file_name = "pump_commands.csv"
    
    # Adjust the current time by the given lag
    adjusted_time = datetime.now() + timedelta(seconds=lag)
    
    # Format timestamp as desired
    timestamp = adjusted_time.strftime('%Y-%m-%d-%H-%M-%S')
    
    create_csv_if_not_exists(file_name,["time", "pump", "command"])
    
    with open(file_name, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([timestamp, pump, command])

def read_pump_commands():
    file_name = "pump_commands.csv"
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
    exit()

def manage_pumps(pump_setting):
    global pump_status
    
    for pump, status in pump_setting.items():
        if pump_status[pump] != status:
            print(f"Current pump setting: {pump_setting}")
            print(f"Current pump status: {pump_status}")
            # Turn on pump
            if status == 1 and pump_status[pump] == 0:
                # Implement the logic to turn on the pump here
                print(f"Turning ON Pump {pump}")
                pump_status[pump] = 1
            
            # Turn off pump
            elif status == 0 and pump_status[pump] == 1:
                # Implement the logic to turn off the pump here
                print(f"Turning OFF Pump {pump}")
                pump_status[pump] = 0

on_lag = 5
off_lag = 10

def main():
    print("Listening for key presses between 1 and 4...")
    while True:
        pump_commands_housekeeper()
        for i in range(1, 5):  # Listen for keys 1 to 4
            if keyboard.is_pressed(str(i)):
                if keyboard.is_pressed('shift'):
                    print(f"Shift + Key {i} pressed. Issuing OFF command...")
                    issue_pump_command(i, 0, off_lag)  # Issuing OFF command with a possible off_lag
                else:
                    print(f"Key {i} pressed. Issuing ON command...")
                    issue_pump_command(i, 1, on_lag)  # Issuing ON command with a possible on_lag

                while keyboard.is_pressed(str(i)):  # Wait until key is released to prevent continuous key detection
                    pass

        
        manage_pumps(read_pump_commands())

if __name__ == "__main__":
    main()