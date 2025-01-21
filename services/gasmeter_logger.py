"""
Continuously runs and records the state of the gas impulse relay.
"""

from utils.project import *

system_node = JSONNodeAtURL(node_relative_path='system')

if __name__ == "__main__":
    try:
        gasmeter_pin = get_system_setup()['gasmeter']['GPIO']
        set_pin_mode(gasmeter_pin,GPIO.IN,GPIO.PUD_DOWN)
        state = 0
        last_state_1_time = None # The last time the dial was at 1
        while True:
            new_state = read_pin_state(gasmeter_pin)
            if new_state != state:
                log_data({"seconds":datetime.now().strftime('%S'),"gasmeter_pin_state_change":new_state},'gas_consumption/gas_relay_turns.json')
                report(f"State change detected on gas meter relay: {new_state}")
                state = new_state
                if last_state_1_time and state == 1:
                    elapsed_time = (datetime.now() - last_state_1_time).total_seconds()
                    system_node.write({"dial_turn_secs":elapsed_time},'state/gas')
                    last_state_1_time = datetime.now()
                
            time.sleep(random.uniform(0.5, 2.5))

    except KeyboardInterrupt:
        release_pin(gasmeter_pin)
        exit()
