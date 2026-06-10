"""
Export raw deCONZ snapshot.
"""

from utils.project import *

if True:
    settings["log"] = False
    settings["verbosity"] = True


DECONZ_SNAPSHOT_RELATIVE_PATH = "dev/deconz_snapshot.json"


def export_deconz_snapshot():
    deconz_state = read_deconz_state()

    snapshot = {
        "timestamp": timestamp(),
        "sensors": {},
        "lights": {},
    }

    for device_id, device in deconz_state.sensors.items():
        snapshot["sensors"][str(device_id)] = device.raw

    for device_id, device in deconz_state.lights.items():
        snapshot["lights"][str(device_id)] = device.raw

    export_dict_as_json(snapshot, DECONZ_SNAPSHOT_RELATIVE_PATH)

    return snapshot


if __name__ == "__main__":
    snapshot = export_deconz_snapshot()
    print(f"exported {len(snapshot['sensors'])} sensors and {len(snapshot['lights'])} lights")
    print(DECONZ_SNAPSHOT_RELATIVE_PATH)