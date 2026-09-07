"""
Reads and logs submeter impulses from two Shelly Plus I4 devices.
"""

from utils.project import *
from utils.shelly_discovery import (
    build_shelly_resolver,
    load_shelly_config,
)

PROJECT_ROOT = get_project_root()
SHELLY_CONFIG = load_shelly_config(PROJECT_ROOT)
SHELLY_RESOLVER = build_shelly_resolver(PROJECT_ROOT, SHELLY_CONFIG)
SUBMETERS = SHELLY_CONFIG["submeters"]
DEVICE_SPECS = SHELLY_CONFIG["devices"]
RECONNECT_DELAY_SECONDS = float(
    SHELLY_CONFIG["discovery"].get("reconnect_delay_seconds", 10)
)

LOCK_PATH = os.path.join(
    get_project_root(),
    "data",
    "locks",
    "submeters_service.lock",
)

system_node = JSONNodeAtURL(node_relative_path='system')
write_lock = threading.Lock()


def make_event_handler(device_name: str, input_lookup: dict[int, str]):

    def handle_event(event):
        out = {
            "timestamp": event["timestamp"],
            "submeter": input_lookup.get(event["input_id"], f"input_{event['input_id']}"),
        }

        with write_lock:
            #system_node.write({"last_press": out}, "state/submeters")
            log_data(out, "electricity/submeters.json")
            report(json.dumps(out, ensure_ascii=False))

    return handle_event


def run_listener(device_name: str):
    input_lookup = {
        int(input_id): submeter
        for input_id, submeter in SUBMETERS[device_name]["inputs"].items()
    }

    while True:
        try:
            device = SHELLY_RESOLVER.resolve_one(
                device_name,
                DEVICE_SPECS[device_name],
            )
            report(
                f"listening for {device_name} impulses at {device['ip']} "
                f"({device['mac']})"
            )
            listen_shelly_single_pushes(
                ip=device["ip"],
                event_handler=make_event_handler(device_name, input_lookup),
            )
        except Exception as e:
            report(
                f"{device_name} listener unavailable: {e}; "
                f"retrying in {RECONNECT_DELAY_SECONDS:g} seconds"
            )
            time.sleep(RECONNECT_DELAY_SECONDS)


success = False
os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)

try:
    with filelock.FileLock(LOCK_PATH, timeout=0):
        threads = []

        for device_name in SUBMETERS:
            thread = threading.Thread(
                target=run_listener,
                args=(device_name,),
                daemon=False,
                name=f"submeter_listener_{device_name}",
            )
            thread.start()
            threads.append(thread)

        success = True
        log({"success": success})
        report("electric submeter listeners started")

        for thread in threads:
            thread.join()

except filelock.Timeout:
    report("electric submeter listener already running")

except ModuleException as e:
    ServiceException(
        "Module error while trying to read and log electric submeter impulses",
        original_exception=e,
        severity=2
    )

except Exception:
    ServiceException(
        "Unexpected error while trying to read and log electric submeter impulses",
        severity=2
    )
