from utils.project import *

from collections import defaultdict
import csv
import json
import os
import requests
import sys


IGNORED_STATE_KEYS = {
    "lastupdated",
    "reachable",
}


PARAMETER_LABELS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "pressure": "pressure",
    "co2": "co2",
    "presence": "presence",
    "open": "open/close",
    "lightlevel": "light level",
    "lux": "illuminance",
    "dark": "dark",
    "daylight": "daylight",
    "buttonevent": "button event",
    "power": "power",
    "current": "current",
    "voltage": "voltage",
    "consumption": "energy consumption",
    "fire": "fire",
    "water": "water leak",
    "vibration": "vibration",
    "airquality": "air quality",
}


def first_present(*vals, default="unknown"):
    for val in vals:
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return default


def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def deconz_base_url():
    deconz = get_deconz_access_params()
    return f"{deconz['api_url'].strip().rstrip('/')}/{deconz['api_key'].strip()}"


def get_deconz_json(path, timeout=10):
    url = f"{deconz_base_url()}/{path.strip('/')}"
    response = requests.get(url, timeout=timeout)

    if response.status_code == 404:
        return None

    response.raise_for_status()
    return response.json()


def device_key_from_uniqueid(uniqueid):
    if not uniqueid:
        return None

    return str(uniqueid).split("-")[0].strip().lower()


def parameters_from_sensor(raw):
    state = raw.get("state", {})
    params = set()

    for key in state:
        if key in IGNORED_STATE_KEYS:
            continue

        params.add(PARAMETER_LABELS.get(key, key))

    return params


def collect_from_devices_endpoint():
    devices = get_deconz_json("devices")

    if not isinstance(devices, dict):
        return None

    collected = {}

    for device_id, raw in devices.items():
        if not isinstance(raw, dict):
            continue

        key = first_present(
            raw.get("uniqueid"),
            raw.get("mac"),
            raw.get("address"),
            device_id,
            default=device_id,
        ).lower()

        collected[key] = {
            "manufacturer": first_present(
                raw.get("manufacturername"),
                raw.get("manufacturer"),
            ),
            "unit": first_present(
                raw.get("productid"),
                raw.get("productname"),
                raw.get("modelid"),
                raw.get("type"),
            ),
            "names": {
                first_present(
                    raw.get("name"),
                    raw.get("productname"),
                    raw.get("modelid"),
                    default=key,
                )
            },
            "measured_parameters": set(),
        }

    return collected


def merge_sensor_and_light_data(collected):
    for endpoint in ["sensors", "lights"]:
        items = get_deconz_json(endpoint)

        if not isinstance(items, dict):
            continue

        for item_id, raw in items.items():
            if not isinstance(raw, dict):
                continue

            uniqueid = raw.get("uniqueid")
            key = device_key_from_uniqueid(uniqueid)

            if key is None:
                key = f"{endpoint}:{item_id}"

            if key not in collected:
                collected[key] = {
                    "manufacturer": first_present(
                        raw.get("manufacturername"),
                        raw.get("manufacturer"),
                    ),
                    "unit": first_present(
                        raw.get("productid"),
                        raw.get("productname"),
                        raw.get("modelid"),
                        raw.get("type"),
                    ),
                    "names": set(),
                    "measured_parameters": set(),
                }

            collected[key]["names"].add(
                first_present(raw.get("name"), default=f"{endpoint}:{item_id}")
            )

            if endpoint == "sensors":
                collected[key]["measured_parameters"].update(
                    parameters_from_sensor(raw)
                )

    return collected


def collect_physical_devices():
    collected = collect_from_devices_endpoint()
    source = "devices_plus_sensors"

    if not collected:
        collected = {}
        source = "sensors_lights_deduplicated_by_uniqueid"

    collected = merge_sensor_and_light_data(collected)

    return collected, source


def summarize_units(physical_devices):
    grouped = defaultdict(lambda: {
        "manufacturer": None,
        "unit": None,
        "names": set(),
        "measured_parameters": set(),
        "count": 0,
    })

    for device in physical_devices.values():
        manufacturer = device["manufacturer"]
        unit = device["unit"]
        group_key = (manufacturer, unit)

        grouped[group_key]["manufacturer"] = manufacturer
        grouped[group_key]["unit"] = unit
        grouped[group_key]["count"] += 1
        grouped[group_key]["names"].update(device["names"])
        grouped[group_key]["measured_parameters"].update(device["measured_parameters"])

    out = []

    for _, group in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1])):
        out.append({
            "manufacturer": group["manufacturer"],
            "unit": group["unit"],
            "how_many_in_the_network": group["count"],
            "names": sorted(group["names"]),
            "measured_parameters": sorted(group["measured_parameters"]),
        })

    return out


def build_report():
    physical_devices, source = collect_physical_devices()

    return {
        "timestamp": timestamp(),
        "source": source,
        "units": summarize_units(physical_devices),
    }


def export_json(report, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)


def export_csv(report, path):
    rows = report["units"]

    fieldnames = [
        "manufacturer",
        "unit",
        "how_many_in_the_network",
        "names",
        "measured_parameters",
    ]

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({
                "manufacturer": row["manufacturer"],
                "unit": row["unit"],
                "how_many_in_the_network": row["how_many_in_the_network"],
                "names": "; ".join(row["names"]),
                "measured_parameters": "; ".join(row["measured_parameters"]),
            })


def export_report(report):
    out_dir = script_dir()

    json_path = os.path.join(out_dir, "unit_report.json")
    csv_path = os.path.join(out_dir, "unit_report.csv")

    export_json(report, json_path)
    export_csv(report, csv_path)

    return {
        "json_path": json_path,
        "csv_path": csv_path,
    }


if __name__ == "__main__":
    try:
        report_data = build_report()
        paths = export_report(report_data)

        print(json.dumps({
            "timestamp": report_data["timestamp"],
            "json_path": paths["json_path"],
            "csv_path": paths["csv_path"],
            "unit_type_count": len(report_data["units"]),
        }, indent=4, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({
            "timestamp": timestamp(),
            "error": str(e),
        }, indent=4, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)