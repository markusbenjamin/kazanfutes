"""
Makes sure all lights are in the state desired.
"""
from utils.project import *

settings['dev'] = False

if settings['dev']:
    settings['verbose'] = True
    settings['log'] = False

success = False
try:
    default_state = {
        'on':True,
        'ct':153,
        'bri':255
    }

    overrides = {
        'pult':{'on':False},
        'trafohaz':{'on':False},
        'oktopusz':{'bri':180}
    }

    for id,info in read_lights():
        name = info.raw['name']
        reported_state = info.raw['state']
    
        desired_state = default_state
        if name in overrides:
            for key, val in overrides[name].items():
                desired_state[key] = val

        for key in default_state.keys():
            print(f"{reported_state[key]}, {desired_state[key]}")
            if reported_state[key] != desired_state[key]:
                set_light_state(id, name, desired_state)
        
        report("Light states set accordingly.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to set light states", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to set light states", severity = 2)

# Log execution
log({"success":success})