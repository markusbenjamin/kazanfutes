class MockGPIO:
    # Constants
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    PUD_OFF = "PUD_OFF"
    PUD_DOWN = "PUD_DOWN"
    PUD_UP = "PUD_UP"
    
    # Mock functions
    @staticmethod
    def setmode(mode):
        print(f"GPIO setmode({mode}) called.")
    
    @staticmethod
    def setup(pin, mode, pull_up_down=None):
        print(f"GPIO setup(pin={pin}, mode={mode}, pull_up_down={pull_up_down}) called.")
    
    @staticmethod
    def output(pin, state):
        print(f"GPIO output(pin={pin}, state={state}) called.")
    
    @staticmethod
    def input(pin):
        print(f"GPIO input(pin={pin}) called.")
        return GPIO.LOW  # Default to LOW for testing
    
    @staticmethod
    def cleanup():
        print("GPIO cleanup() called.")