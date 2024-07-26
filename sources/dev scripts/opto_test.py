import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)
GPIOpin = int(input("pin? "))
GPIO.setup(GPIOpin, GPIO.OUT)  # For driving the optocoupler LED

current_state = False

try:
    while True:
        button_input = input("Press 'o' to toggle GPIO: ")
        if button_input == 'o':
            current_state = not current_state
            if current_state:
                print('GPIO on')
            else: 
                print('GPIO off')
            GPIO.output(GPIOpin, current_state)

except KeyboardInterrupt:
    GPIO.setup(GPIOpin, GPIO.OUT)
    GPIO.output(GPIOpin, GPIO.HIGH)
