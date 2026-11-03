"""
Logs heatmeter states.
Writes lean selected values to the system node as:
system/state/heatmeters/last_updated
system/state/heatmeters/1/temp
system/state/heatmeters/1/flow
system/state/heatmeters/1/power
...
"""

from utils.project import *
from utils.heat_delivery_formatter import heatmeter_live_snapshot

success = False
try:
    # full original log payload
    vals = {}
    for meter in [1, 2, 3, 4]:
        measured_fields = [
            "flow_temperature_c",
            "return_temperature_c",
            "volume_flow_m3h",
            "power_w",
            "energy_kwh",
            "volume_m3",
        ]
        vals[meter] = get_heatmeter_data(meter, fields=measured_fields)

    ts = timestamp()

    # lean system-state write
    heatmeters_state = heatmeter_live_snapshot(vals, ts)

    system_node = JSONNodeAtURL(node_relative_path="system")
    system_node.write(
        {"heatmeters": heatmeters_state},
        "state",
    )

    # original full log
    log_data(
        {"timestamp": ts, "states": vals},
        "heat_delivery/heatmeters_state.json",
    )

    report("Heatmeter states acquired, system node updated, and full state logged.", verbose=True)
    success = True

except ModuleException as e:
    ServiceException(
        "Module error while trying to acquire heatmeter states",
        original_exception=e,
        severity=2,
    )

except Exception:
    ServiceException(
        "Module error while trying to acquire heatmeter states",
        severity=2,
    )

log({"success": success})
