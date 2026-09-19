"""
Continuously runs and records open/close events from deCONZ sensors.
"""

from utils.project import *


UNNAMED_PARASOLL_PREFIX = "PARASOLL Door/Window "


def is_unrenamed_parasoll(name):
    return name.startswith(UNNAMED_PARASOLL_PREFIX)

# system_node = JSONNodeAtURL(node_relative_path='system')

if __name__ == "__main__":
    try:
        state = get_open_close_states()

        for name, sensor_state in state.items():
            if is_unrenamed_parasoll(name):
                continue

            event = {
                "sensor_name": name,
                "event": "startup",
                "state": "open" if sensor_state["open"] else "closed",
            }

            log_data(event, "open_close/open_close_events.json")
            report(f"Startup open/close state for {name}: {event['event']}")

        report(f"Open/close logger initialized with {len(state)} sensors.")

        while True:
            new_state = get_open_close_states()

            for name, sensor_state in new_state.items():
                if is_unrenamed_parasoll(name):
                    continue

                if name not in state:
                    event = {
                        "sensor_name": name,
                        "event": "new_sensor",
                        "state": "open" if sensor_state["open"] else "closed",
                    }

                    log_data(event, "open_close/open_close_events.json")
                    report(f"New open/close sensor detected: {name}: {event['event']}")

                    state[name] = sensor_state
                    continue

                prev_state = state[name]

                if sensor_state["open"] != prev_state["open"]:
                    event = {
                        "sensor_name": name,
                        "event": "opened" if sensor_state["open"] else "closed",
                        "state": "open" if sensor_state["open"] else "closed",
                    }

                    log_data(event, "open_close/open_close_events.json")

                    # system_node.write(
                    #     {
                    #         name: {
                    #             "state": event["state"],
                    #             "last_event": timestamp(),
                    #         }
                    #     },
                    #     "state/open_close"
                    # )

                    report(f"Open/close event on {name}: {event['event']}")

                state[name] = sensor_state

            time.sleep(random.uniform(0.5, 2.5))

    except KeyboardInterrupt:
        exit()
    except Exception:
        ServiceException("Error while trying to log open/close events", severity=1)
        exit()