"""
Continuously runs and records the state of the gas impulse relay.
"""

from utils.project import *

if __name__ == "__main__":
    try:
        gasmeter_pin = get_system_config()['gasmeter']['GPIO']
        set_pin_mode(gasmeter_pin,GPIO.IN,GPIO.PUD_DOWN)
        state = 0
        while True:
            new_state = read_pin_state(gasmeter_pin)
            if new_state != state:
                log_data({"gasmeter_pin_state_change":new_state})
                state = new_state
                
            time.sleep(2.5)

    except KeyboardInterrupt:
        release_pin(gasmeter_pin)
        exit()
