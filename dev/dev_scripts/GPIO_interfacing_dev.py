from utils.project import *
import RPi.GPIO as GPIO

def set_pin_state(pin, state):
    """
    Sets the specified GPIO pin to the given state (HIGH or LOW).
    
    Args:
    pin (int): The GPIO pin number.
    state (bool): Set to True for HIGH, False for LOW.
    """
    # Set GPIO mode to BCM
    GPIO.setmode(GPIO.BCM)

    # Set the pin as output and set its state
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.HIGH if state == 1 else GPIO.LOW)

def read_pin_state(pin):
    """
    Reads the state of the specified GPIO pin.
    
    Args:
    pin (int): The GPIO pin number.
    
    Returns:
    int: The state of the pin (1 = HIGH, 0 = LOW).
    """
    # Set GPIO mode to BCM
    GPIO.setmode(GPIO.BCM)

    GPIO.setup(pin, GPIO.OUT)
    
    # Read the state of the pin
    return GPIO.input(pin)

if __name__ == '__main__':
    boiler_pin = get_system_config()['boiler']['GPIO']
    set_pin_state(boiler_pin, 0)
    while True:
        print(read_pin_state(boiler_pin))
        time.sleep(10)
        set_pin_state(boiler_pin, 1)