import time

# Set the cycle times in minutes
cycle_refresh_and_update = 0.1
cycle_compare_and_command = 0.2
cycle_control_pumps = 0.3
cycle_control_albatros = 0.4

def refresh_and_update():
    print("Executing refresh_and_update")

def compare_and_command():
    print("Executing compare_and_command")

def control_pumps():
    print("Executing control_pumps")

def control_albatros():
    print("Executing control_albatros")

def main():
    while True:
        current_seconds = int(time.time())
        if current_seconds % (int(cycle_refresh_and_update * 60)) == 0:
            refresh_and_update()
        if current_seconds % (int(cycle_compare_and_command * 60)) == 0:
            compare_and_command()
        if current_seconds % (int(cycle_control_pumps * 60)) == 0:
            control_pumps()
        if current_seconds % (int(cycle_control_albatros * 60)) == 0:
            control_albatros()
        time.sleep(1)  # Sleep for a short duration to prevent busy-waiting

if __name__ == "__main__":
    main()