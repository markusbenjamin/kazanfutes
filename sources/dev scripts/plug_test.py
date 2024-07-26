import tinytuya
import time
import json

def get_plug_state(device):
    data = device.status()
    return data.get('dps', {}).get('1', False)

def set_plug_state(device, state):
    if state:
        device.turn_on()
    else:
        device.turn_off()

def extract_plugs_from_file(filename):
    with open(filename, 'r') as file:
        plugs_data = json.load(file)
    return plugs_data

def main():
    # Load the plug data from plug_info.json file
    filename = 'plug_info.json'
    plugs_info = extract_plugs_from_file(filename)
    
    # Transform the format to match the one expected by tinytuya
    plugs_info = [
        {
            "dev_id": plug["id"],
            "address": plug["ip"],
            "local_key": plug["key"],
            "version": 3.3
        }
        for plug in plugs_info
    ]

    # List to keep track of the initial state of each plug
    original_states = []

    devices = []
    for plug in plugs_info:
        d = tinytuya.OutletDevice(
            dev_id=plug["dev_id"],
            address=plug["address"],
            local_key=plug["local_key"],
            version=plug["version"]
        )

        # Store the device and its original state
        devices.append(d)
        original_states.append(get_plug_state(d))

    try:
        while True:
            for device in devices:
                # Turn On for 1 second
                device.turn_on()
                time.sleep(1)

                # Turn Off for 1 second
                device.turn_off()
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nRestoring original states...")
        for device, state in zip(devices, original_states):
            set_plug_state(device, state)
        print("Original states restored!")

if __name__ == "__main__":
    main()