from utils.project import *

if __name__ == '__main__':
    print(set_all_pumps(1))
    print(get_pump_states())
    start = time.time()
    while time.time() - start < 10:
        time.sleep(0.1) 
    print(set_all_pumps(0))
    print(get_pump_states())
