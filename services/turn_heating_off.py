from utils.project import *

settings["log"] = False
settings["verbosity"] = True
settings["dev"] = True

report("\nHEATING OFF")

success = False
shutdown_error = None

try:
    system_node = JSONNodeAtURL(node_relative_path="system")
    system_node.write({"last_updated": timestamp(), "error": False, "where": None}, "control/error")

    success = shutdown_heating(calibrate_thermostats=True)

except ModuleException as e:
    shutdown_error = str(e)
    system_node.write({"last_updated": timestamp(), "error": True, "where": "shutdown_heating"}, "control/error")
    ServiceException("Module error while shutting down heating", original_exception=e, severity=3)

except Exception as e:
    shutdown_error = str(e)
    system_node.write({"last_updated": timestamp(), "error": True, "where": "shutdown_heating"}, "control/error")
    ServiceException("Unexpected error while shutting down heating", severity=3)

try:
    system_state = load_json_to_dict("system/state.json")

except Exception:
    system_state = {}

try:
    system_state["last_updated"] = timestamp()
    system_state["mode"] = "heating_off"
    system_state["shutdown_success"] = success
    system_state["shutdown_error"] = shutdown_error

    try:
        system_state["pump_states"] = get_pump_states()
    except Exception as e:
        system_state["pump_states_error"] = str(e)

    try:
        system_state["boiler_state"] = get_boiler_state()
    except Exception as e:
        system_state["boiler_state_error"] = str(e)

    try:
        rooms = get_rooms_info()
        valve_states = {}

        for room, info in rooms.items():
            valve_states[room] = []

            if isinstance(info["thermostats"], str):
                for th in (t.strip() for t in info["thermostats"].split(";") if t.strip()):
                    valve_states[room].append(get_thermostat_state_by_id(th, ["valve"])["valve"])
            elif info["thermostats"]:
                valve_states[room].append(100)
            else:
                valve_states[room].append(0)

        system_state["valve_states"] = valve_states

    except Exception as e:
        system_state["valve_states_error"] = str(e)

    system_node.write(system_state, "state")
    export_dict_as_json(system_state, "system/state.json")

    report("Heating-off state exported.")

except ModuleException as e:
    system_node.write({"last_updated": timestamp(), "error": True, "where": "system_state_export"}, "control/error")
    ServiceException("Module error while exporting heating-off state", original_exception=e, severity=3)

except Exception:
    system_node.write({"last_updated": timestamp(), "error": True, "where": "system_state_export"}, "control/error")
    ServiceException("Unexpected error while exporting heating-off state", severity=3)