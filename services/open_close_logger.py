"""
Continuously runs and records open/close events from open / close sensors.
"""

from utils.project import *

# system_node = JSONNodeAtURL(node_relative_path='system')

if __name__ == "__main__":
    try:
        state = get_open_close_states()
        report(f"Open/close logger initialized with {len(state)} sensors.")

        while True:
            new_state = get_open_close_states()

            for name, sensor_state in new_state.items():
                if name not in state:
                    state[name] = sensor_state
                    report(f"New open/close sensor detected: {name}")
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