"""
Reads and logs submeter impulses from two Shelly Plus I4 devices.
"""

from utils.project import *

SHELLIES = {
    "192.168.101.85": {
        0: "keramia",
        1: "hm division",
        2: "ovi",
        3: "merce",
    },
    "192.168.101.76": {
        0: "studio",
        1: "szgk",
        2: "golya",
        3: "edzoterem",
    },
}

LOCK_PATH = os.path.join(
    get_project_root(),
    "data",
    "locks",
    "submeters_service.lock",
)

system_node = JSONNodeAtURL(node_relative_path='system')
write_lock = threading.Lock()


def make_event_handler(ip: str):
    input_lookup = SHELLIES[ip]

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


def run_listener(ip: str):
    listen_shelly_single_pushes(
        ip=ip,
        event_handler=make_event_handler(ip),
    )


success = False
os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)

try:
    with filelock.FileLock(LOCK_PATH, timeout=0):
        threads = []

        for ip in SHELLIES:
            thread = threading.Thread(
                target=run_listener,
                args=(ip,),
                daemon=False,
                name=f"submeter_listener_{ip}",
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