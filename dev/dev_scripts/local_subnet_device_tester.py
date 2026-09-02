#!/usr/bin/env python3
"""
Read-only health checker for devices reached directly through the Raspberry Pi's
local application subnet, plus the locally attached ConBee II/deCONZ coordinator.

Included:
- Tuya pump smart plugs from system/setup.json
- Modbus heat-meter gateway and meters 1..4
- HomeWizard P1 meter
- ConBee II USB coordinator + deCONZ API

Intentionally excluded:
- Shelly devices on the separate 192.168.101.x subnet
- Zigbee end devices (bulbs, Sonoff sensors, Danfoss valves, Parasoll, etc.);
  those are reached through deCONZ rather than directly through the LAN
- Internet/cloud services

This script performs read-only/probe operations only. A device being switched
off (for example a Tuya pump plug whose relay state is off) is still reported OK
when it responds correctly.

Run from repository root:
    python dev/dev_scripts/local_subnet_device_tester.py

Exit code:
    0 = every required endpoint OK
    1 = at least one endpoint NOT OK
"""

from __future__ import annotations

import glob
import socket
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

import requests

import utils.project as project


project.settings["log"] = False
project.settings["verbosity"] = False

HEATMETER_IP = "192.168.29.25"
HEATMETER_PORT = 502
HEATMETER_IDS = (1, 2, 3, 4)
HOMEWIZARD_URL = "http://192.168.29.88/api/v1/data"


@dataclass
class CheckResult:
    name: str
    address: str
    ok: bool
    detail: str = ""


def _safe_check(name: str, address: str, func: Callable[[], str | None]) -> CheckResult:
    try:
        detail = func() or ""
        return CheckResult(name=name, address=address, ok=True, detail=detail)
    except Exception as exc:
        return CheckResult(
            name=name,
            address=address,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> str:
    with socket.create_connection((host, port), timeout=timeout):
        return f"TCP {port} responds"


def _check_tuya_pump(cycle: str) -> str:
    # Read only: the return value may be True or False depending on the relay
    # state. Either value proves that the plug answered successfully.
    state = project.get_pump_state(cycle)
    if not isinstance(state, bool):
        raise RuntimeError(f"unexpected pump state response: {state!r}")
    return f"relay={'ON' if state else 'OFF'}"


def _check_heatmeter(meter_id: int) -> str:
    values = project.get_heatmeter_data(
        meter_id,
        ip=HEATMETER_IP,
        port=HEATMETER_PORT,
        fields=["flow_temperature_c"],
    )
    if not isinstance(values, dict):
        raise RuntimeError(f"unexpected response: {values!r}")
    if values.get("flow_temperature_c") is None:
        raise RuntimeError(f"no flow_temperature_c returned: {values!r}")
    return f"flow_temp={values['flow_temperature_c']} C"


def _check_homewizard() -> str:
    response = requests.get(HOMEWIZARD_URL, timeout=5)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("HomeWizard response is not a JSON object")
    if "active_power_w" not in data:
        raise RuntimeError("HomeWizard response lacks active_power_w")
    return f"active_power={data.get('active_power_w')} W"


def _conbee_usb_present() -> tuple[bool, str]:
    """Look for a locally attached ConBee II without modifying anything."""
    # First use stable /dev/serial aliases when available.
    for path in glob.glob("/dev/serial/by-id/*"):
        lowered = path.lower()
        if "conbee" in lowered or "dresden" in lowered:
            return True, path

    # Fall back to lsusb. ConBee II normally identifies as Dresden Elektronik;
    # 1cf1 is the Dresden Elektronik USB vendor ID.
    try:
        proc = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        return False, "lsusb unavailable and no matching /dev/serial/by-id entry"

    text = proc.stdout or ""
    for line in text.splitlines():
        lowered = line.lower()
        if "conbee" in lowered or "dresden elektronik" in lowered or "1cf1:" in lowered:
            return True, line.strip()

    return False, "ConBee II not found in /dev/serial/by-id or lsusb"


def _check_conbee_deconz() -> str:
    usb_ok, usb_detail = _conbee_usb_present()
    if not usb_ok:
        raise RuntimeError(usb_detail)

    # Existing project helper performs a real deCONZ state refresh. This checks
    # more than whether port 80 is open: the deCONZ API must answer correctly.
    state = project.read_deconz_state()
    if state is None:
        raise RuntimeError("read_deconz_state() returned None")

    if not hasattr(state, "sensors") or not hasattr(state, "lights"):
        raise RuntimeError("deCONZ state did not expose sensors/lights collections")

    sensor_count = len(state.sensors)
    light_count = len(state.lights)
    return f"USB present; deCONZ API OK; sensors={sensor_count}, lights={light_count}"


def collect_results() -> list[CheckResult]:
    results: list[CheckResult] = []

    # Tuya devices are taken dynamically from the existing project setup so the
    # tester follows future IP/config changes without duplicating secrets here.
    try:
        pumps = project.get_pumps_info()
    except Exception as exc:
        results.append(
            CheckResult(
                name="Tuya pump configuration",
                address="system/setup.json",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )
        pumps = {}

    for cycle, info in sorted(pumps.items(), key=lambda item: str(item[0])):
        cycle = str(cycle)
        ip = str((info or {}).get("ip") or "unknown")
        results.append(
            _safe_check(
                name=f"Tuya pump {cycle}",
                address=ip,
                func=lambda cycle=cycle: _check_tuya_pump(cycle),
            )
        )

    # Report the Modbus TCP gateway separately. If it is down, all meter reads
    # will also fail, making the root cause immediately visible.
    results.append(
        _safe_check(
            name="Heatmeter Modbus gateway",
            address=f"{HEATMETER_IP}:{HEATMETER_PORT}",
            func=lambda: _tcp_probe(HEATMETER_IP, HEATMETER_PORT),
        )
    )

    for meter_id in HEATMETER_IDS:
        results.append(
            _safe_check(
                name=f"Heatmeter {meter_id}",
                address=f"{HEATMETER_IP} / meter {meter_id}",
                func=lambda meter_id=meter_id: _check_heatmeter(meter_id),
            )
        )

    results.append(
        _safe_check(
            name="HomeWizard P1",
            address="192.168.29.88",
            func=_check_homewizard,
        )
    )

    results.append(
        _safe_check(
            name="ConBee II + deCONZ",
            address="local USB / local deCONZ API",
            func=_check_conbee_deconz,
        )
    )

    return results


def print_report(results: list[CheckResult]) -> None:
    print("LOCAL SUBNET / COORDINATOR HEALTH")
    print("=" * 72)

    name_width = max([len(result.name) for result in results] + [6])
    address_width = max([len(result.address) for result in results] + [7])

    for result in results:
        status = "OK" if result.ok else "NOT OK"
        print(f"{result.name:<{name_width}}  {result.address:<{address_width}}  {status}")
        if not result.ok and result.detail:
            print(f"  -> {result.detail}")

    print("=" * 72)
    overall = all(result.ok for result in results)
    print(f"OVERALL: {'OK' if overall else 'NOT OK'}")


def main() -> int:
    results = collect_results()
    print_report(results)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
