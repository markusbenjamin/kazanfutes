"""
Logs heatmeter states.
"""

from utils.project import *

success = False
try:
    # Log heatmeter states
    vals = {}
    for meter in [1,2,3,4]:
        measured_fields = [
                'flow_temperature_c',      # Direct sensor measurement
                'return_temperature_c',    # Direct sensor measurement
                'volume_flow_m3h',         # Direct sensor measurement
                'power_w',                 # Metered (integrated)
                'energy_kwh',              # Metered (integrated power over time)
                'volume_m3'                # Metered (integrated flow over time)
            ]
        vals[meter] = get_heatmeter_data(meter, fields=measured_fields)
    log_data({"timestamp": timestamp(), "states":vals},'heat_delivery/heatmeters_state.json')
    report("Heatmeter states acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to acquire heatmeter states", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to acquire heatmeter states", severity = 2)

# Log execution
log({"success":success})