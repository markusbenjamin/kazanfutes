from utils.project import *

def get_pumps_power(pumps):
    """
    Return {'power_w': float, 'current_a': float, 'voltage_v': float}
    using Tuya DPs 19, 18, 20.
    """
    power = {}
    for pump in pumps:
        dev = connect_to_pump(pump)
        if dev is None:
            raise ModuleException(f"no device for '{pump}'")

        dev.set_dpsUsed({'18': None, '19': None, '20': None})  # current, power, voltage
        dps = dev.status()['dps']

        power[pump] = int(dps['19'])/10
    
    return power

print(get_pumps_power(['1','2','3','4']))
