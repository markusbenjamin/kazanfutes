from utils.project import *
#pump_info = get_pumps_info()
#print(pump_info)
#
#pump = '1'
#
## Connect to Device
#d = tinytuya.OutletDevice(
#    dev_id = pump_info[pump]['id'],
#    address = pump_info[pump]['ip'],      # Or set to 'Auto' to auto-discover IP address
#    local_key = pump_info[pump]['key'], 
#    version = 3.3)
#
## Get Status
#data = d.status() 
#print('set_status() result %r' % data)
#
## Turn On
#d.turn_on()
#
#time.sleep(5)
#
## Turn Off
#d.turn_off()

def get_pump_states():
    """
    Returns a dict with 0 or 1 or None if cannot read for each pump.
    """
    try:
        state = {'1':None,'2':None,'3':None,'4':None}
        pump_info = get_pumps_info()
        for pump,info in pump_info.items():
            state[pump] = get_pump_state(pump)
        return state
    except Exception:
        raise ModuleException(f"couldn't read pump states")

def get_pump_state(pump:str):
    """
    Returns a faux val for development purposes for now.
    """
    try:
        device = connect_to_pump(pump)
        return int(device.status()['dps']['1']) # This path encodes the on/off state in the JSON reply
    except Exception:
        raise ModuleException(f"couldn't read state of pump {pump}")

def connect_to_pump(pump:str):
    """
    Connects to a pump via tinytuya and returns an OutletDevice object.
    """
    pump_info = get_pumps_info()
    device = tinytuya.OutletDevice(
        dev_id = pump_info[pump]['id'],
        address = pump_info[pump]['ip'],      # Or set to 'Auto' to auto-discover IP address
        local_key = pump_info[pump]['key'], 
        version = 3.3)
    return device

def set_pump_state(pump:str,state:int):
    """
    Sets the state of a given pump via Tuya interfacing.
    Warning: returns success not state.
    """
    success = False
    try:
        device = connect_to_pump(pump)
        if state:
            success = device.turn_on()['dps']['1']
        else:
            success = device.turn_off()['dps']['1'] == False
    except Exception:
        raise ModuleException(f"couldn't turn pump {pump} {["OFF","ON"][state]}")
    finally:
        return success

def set_all_pumps(state:int):
    """
    Turn all pumps on or off at once. Returns a dict of successes (and __not__ states!).
    """
    success = {"1":False,"2":False,"3":False,"4":False}
    try:
        pump_info = get_pumps_info()
        for pump,info in pump_info.items():
            success[pump] = set_pump_state(pump,state)
    except Exception:
        raise ModuleException(f"couldn't turn all pumps {["OFF","ON"][state]}")
    finally:
        return success

if __name__ == '__main__':
    print(set_all_pumps(0))