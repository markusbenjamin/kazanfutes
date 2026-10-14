"""Read boiler smart-plug power and relay state without changing either device."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any

import requests

from utils.shelly_discovery import build_shelly_resolver, load_shelly_config, normalize_mac


def _reading(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a numeric meter reading")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite meter reading")
    return number


def collect_boiler_plugs(project_root: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """Return one stable-MAC observation per configured boiler power plug."""
    observed_at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    config = load_shelly_config(project_root)
    names = config.get("boiler_power_devices", [])
    specs = {name: config["devices"][name] for name in names}
    resolver = build_shelly_resolver(project_root, config)
    try:
        resolved, errors = resolver.resolve_many(specs)
    except Exception as error:
        resolved = {}
        errors = {name: f"Discovery failed: {type(error).__name__}: {error}" for name in names}

    devices: list[dict[str, Any]] = []
    for name in names:
        mac = normalize_mac(specs[name]["mac"])
        device = {
            "device_id": f"shelly:{mac}",
            "name": name,
            "category": "boiler_power_plug",
            "profile": "boiler_power_plug",
            "hardware_type": "Shelly Plug M Gen3",
            "facts": {
                "reachable": False,
                "collection_error": errors.get(name, "Not found"),
                "last_seen_at": None,
                "measurements": {},
            },
        }
        record = resolved.get(name)
        if record:
            try:
                response = requests.get(
                    f"http://{record['ip']}/rpc/Switch.GetStatus?id=0", timeout=3
                )
                response.raise_for_status()
                status = response.json()
                if not isinstance(status, dict) or not isinstance(status.get("output"), bool):
                    raise ValueError("Switch.GetStatus has no boolean output")
                temperature = status.get("temperature") or {}
                device["facts"] = {
                    "reachable": True,
                    "last_seen_at": observed_at,
                    "output_on": status["output"],
                    "switch_source": status.get("source"),
                    "switch_errors": status.get("errors") or [],
                    "ip": record["ip"],
                    "measurements": {
                        "power_w": _reading(status.get("apower")),
                        "voltage_v": _reading(status.get("voltage")),
                        "current_a": _reading(status.get("current")),
                        "frequency_hz": _reading(status.get("freq")),
                        "device_temperature_c": _reading(temperature.get("tC")),
                    },
                }
            except Exception as error:
                device["facts"]["collection_error"] = (
                    f"Status read failed: {type(error).__name__}: {error}"
                )
        devices.append(device)
    return devices


def boiler_device_ids(project_root: str) -> set[str]:
    """Return the configured stable identities for partial watchdog updates."""
    config = load_shelly_config(project_root)
    return {
        f"shelly:{normalize_mac(config['devices'][name]['mac'])}"
        for name in config.get("boiler_power_devices", [])
    }
