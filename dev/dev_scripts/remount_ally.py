from utils.project import *
import sys
import json


settings["verbosity"] = True


TRV_NAMES = [
    "Golyafeszek_1",
    "Golyafeszek_2",
]

# if empty, remount all found ZHAThermostat devices
# TRV_NAMES = []
TRV_NAMES = []


TIMEOUT_S = 180.0


def resolve_trv(target):
    sensor_id = str(get_thermostat_id_from_name(target))
    return sensor_id, target


def get_targets():
    if TRV_NAMES:
        return TRV_NAMES

    return [
        sensor.raw["name"]
        for _, sensor in read_thermostats()
    ]


def main():
    results = []
    targets = get_targets()

    print("targets:")
    print(json.dumps(targets, indent=2, ensure_ascii=False))

    for target in targets:
        print("\n" + "=" * 60)
        print(f"processing: {target}")

        try:
            sensor_id, name = resolve_trv(target)

            print(
                json.dumps(
                    {
                        "target": target,
                        "resolved_sensor_id": sensor_id,
                        "resolved_name": name,
                        "timeout_s": TIMEOUT_S,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )

            before = get_thermostat_state_by_id(
                sensor_id,
                fields=["mountingmodeactive", "temperature", "lastupdated"],
            )
            print("\nbefore:")
            print(json.dumps(before, indent=2, ensure_ascii=False))

            ok = calibrate_thermostat_by_id(
                sensor_id=sensor_id,
                timeout_s=TIMEOUT_S,
            )

            after = get_thermostat_state_by_id(
                sensor_id,
                fields=["mountingmodeactive", "temperature", "lastupdated"],
            )
            print("\nafter:")
            print(json.dumps(after, indent=2, ensure_ascii=False))

            result = {
                "name": name,
                "sensor_id": sensor_id,
                "success": bool(ok),
            }
            results.append(result)

            if ok:
                print("\ncalibration completed")
            else:
                print("\ncalibration timed out")

        except ModuleException as e:
            print(f"\nERROR: {e}")
            results.append(
                {
                    "name": target,
                    "sensor_id": None,
                    "success": False,
                    "error": str(e),
                }
            )

        except Exception as e:
            print(f"\nUNEXPECTED ERROR: {e}")
            results.append(
                {
                    "name": target,
                    "sensor_id": None,
                    "success": False,
                    "error": str(e),
                }
            )

    print("\n" + "=" * 60)
    print("summary:")
    print(json.dumps(results, indent=2, ensure_ascii=False))

    if all(r["success"] for r in results):
        sys.exit(0)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()