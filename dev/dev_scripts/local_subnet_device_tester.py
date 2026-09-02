#!/usr/bin/env python3
"""
Read-only health checker for devices reached directly through the Raspberry Pi's
local application subnet, plus the locally attached ConBee II/deCONZ coordinator.

Included:
- Tuya pump smart plugs from system/setup.json
- Modbus heat-meter gateway and meters 1..4
- HomeWizard P1 meter
- ConBee II / deCONZ coordinator

Intentionally excluded:
- Shelly devices on the separate 192.168.101.x subnet
- Zigbee end devices (bulbs, Sonoff sensors, Danfoss valves, Parasoll, etc.);
  those are reached through deCONZ rather than directly through the LAN
- Internet/cloud services

Health means that the endpoint returned a valid response. Zero readings and OFF
states are valid and do not count as faults.

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
from typing import Callable

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


def _safe_check(
    name: str,
    address: str,
    func: Callable[[], str | None],
    issue_hint: str,
) -> CheckResult:
    try:
        detail = func() or ""
        return CheckResult(name=name, address=address, ok=True, detail=detail)
    except Exception as exc:
        return CheckResult(
            name=name,
            address=address,
            ok=False,
            detail=f"suspected: {issue_hint}; error: {type(exc).__name__}: {exc}",
        )


def _tcp_probe(host: str, port: int, timeout: float = 3.0) -> str:
    with socket.create_connection((host, port), timeout=timeout):
        return f"TCP {port} responds"


def _check_tuya_pump(cycle: str) -> str:
    """
    A Tuya plug is OK if either its relay-state query or its power query returns
    a valid value. OFF (0) and 0 W are both normal valid responses.
    """
    state = None
    power = None
    state_error = None
    power_error = None

    try:
        state = project.get_pump_state(cycle)
    except Exception as exc:
        state_error = f"{type(exc).__name__}: {exc}"

    try:
        powers = project.get_pump_powers([cycle])
        if isinstance(powers, dict):
            power = powers.get(cycle)
    except Exception as exc:
        power_error = f"{type(exc).__name__}: {exc}"

    state_ok = isinstance(state, (int, bool)) and state in (0, 1)
    power_ok = isinstance(power, (int, float)) and not isinstance(power, bool)

    if not state_ok and not power_ok:
        raise RuntimeError(
            "no valid state or power reply; "
            f"state={state!r} ({state_error or 'invalid response'}), "
            f"power={power!r} ({power_error or 'invalid response'})"
        )

    details = []
    details.append(
        f"relay={'ON' if int(state) == 1 else 'OFF'}" if state_ok else "relay=unavailable"
    )
    details.append(f"power={power} W" if power_ok else "power=unavailable")
    return ", ".join(details)


def _check_heatmeter(meter_id: int) -> str:
    """A meter is OK when a real Modbus measurement comes back, including zero."""
    values = project.get_heatmeter_data(
        meter_id,
        ip=HEATMETER_IP,
        port=HEATMETER_PORT,
        fields=["flow_temperature_c", "power_w"],
    )

    if not isinstance(values, dict):
        raise RuntimeError(f"unexpected response type: {type(values).__name__}")

    flow_temp = values.get("flow_temperature_c")
    power = values.get("power_w")

    flow_ok = isinstance(flow_temp, (int, float)) and not isinstance(flow_temp, bool)
    power_ok = isinstance(power, (int, float)) and not isinstance(power, bool)

    if not flow_ok and not power_ok:
        raise RuntimeError(f"no valid measurement returned: {values!r}")

    details = []
    if flow_ok:
        details.append(f"flow_temp={flow_temp} C")
    if power_ok:
        details.append(f"power={power} W")
    return ", ".join(details)


def _check_homewizard() -> str:
    response = requests.get(HOMEWIZARD_URL, timeout=5)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError("response is not a JSON object")

    # Zero is a valid meter reading; field presence and numeric type are what
    # matter for this health check.
    active_power = data.get("active_power_w")
    voltage_l1 = data.get("active_voltage_l1_v")

    power_ok = isinstance(active_power, (int, float)) and not isinstance(active_power, bool)
    voltage_ok = isinstance(voltage_l1, (int, float)) and not isinstance(voltage_l1, bool)

    if not power_ok and not voltage_ok:
        raise RuntimeError(
            "response lacks valid active_power_w and active_voltage_l1_v readings"
        )

    details = []
    if power_ok:
        details.append(f"active_power={active_power} W")
    if voltage_ok:
        details.append(f"L1={voltage_l1} V")
    return ", ".join(details)


def _conbee_usb_present() -> tuple[bool, str]:
    """Look for a locally attached ConBee II without modifying anything."""
    for path in glob.glob("/dev/serial/by-id/*"):
        lowered = path.lower()
        if "conbee" in lowered or "dresden" in lowered:
            return True, path

    try:
        proc = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        return False, "USB enumeration unavailable"

    text = proc.stdout or ""
    for line in text.splitlines():
        lowered = line.lower()
        if "conbee" in lowered or "dresden elektronik" in lowered or "1cf1:" in lowered:
            return True, line.strip()

    return False, "ConBee II not found by /dev/serial/by-id or lsusb"


def _manager_items(manager, label: str):
    """Enumerate a pydeCONZ resource manager without assuming len() support."""
    if manager is None:
        raise RuntimeError(f"deCONZ {label} manager is missing")
    if not hasattr(manager, "items"):
        raise RuntimeError(f"deCONZ {label} manager has no items() method")
    return list(manager.items())


def _check_conbee_deconz() -> str:
    """
    deCONZ is considered healthy when a real state refresh succeeds and its
    resource managers can be enumerated. USB detection is reported as supporting
    information, but a working deCONZ state refresh is the decisive condition.
    """
    usb_ok, usb_detail = _conbee_usb_present()

    state = project.read_deconz_state()
    if state is None:
        raise RuntimeError("read_deconz_state() returned None")

    sensor_items = _manager_items(getattr(state, "sensors", None), "sensor")
    light_items = _manager_items(getattr(state, "lights", None), "light")

    # In this installation the Zigbee network is populated. An entirely empty
    # state is therefore suspicious even if the API itself answered.
    if not sensor_items and not light_items:
        raise RuntimeError("deCONZ refreshed but returned zero sensor/light resources")

    usb_text = "USB detected" if usb_ok else f"USB not independently detected ({usb_detail})"
    return (
        f"deCONZ state OK; sensors={len(sensor_items)}, lights={len(light_items)}; "
        f"{usb_text}"
    )


def collect_results() -> list[CheckResult]:
    results: list[CheckResult] = []

    try:
        pumps = project.get_pumps_info()
    except Exception as exc:
        results.append(
            CheckResult(
                name="Tuya pump configuration",
                address="system/setup.json",
                ok=False,
                detail=(
                    "suspected: local pump configuration cannot be loaded; "
                    f"error: {type(exc).__name__}: {exc}"
                ),
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
                issue_hint=(
                    "Tuya plug is unreachable, its local key/IP is wrong, or it is not "
                    "returning valid state/power data"
                ),
            )
        )

    results.append(
        _safe_check(
            name="Heatmeter Modbus gateway",
            address=f"{HEATMETER_IP}:{HEATMETER_PORT}",
            func=lambda: _tcp_probe(HEATMETER_IP, HEATMETER_PORT),
            issue_hint=(
                "Modbus TCP gateway is offline, unreachable from the RasPi, or port 502 "
                "is not listening"
            ),
        )
    )

    for meter_id in HEATMETER_IDS:
        results.append(
            _safe_check(
                name=f"Heatmeter {meter_id}",
                address=f"{HEATMETER_IP} / meter {meter_id}",
                func=lambda meter_id=meter_id: _check_heatmeter(meter_id),
                issue_hint=(
                    f"heatmeter {meter_id} is not answering through the Modbus gateway, "
                    "or its register read is failing"
                ),
            )
        )

    results.append(
        _safe_check(
            name="HomeWizard P1",
            address="192.168.29.88",
            func=_check_homewizard,
            issue_hint=(
                "HomeWizard is unreachable, its local API is disabled/failing, or its "
                "meter response is malformed"
            ),
        )
    )

    results.append(
        _safe_check(
            name="ConBee II + deCONZ",
            address="local USB / local deCONZ API",
            func=_check_conbee_deconz,
            issue_hint=(
                "deCONZ cannot refresh/enumerate the Zigbee network; possible deCONZ "
                "service, API credential, serial-device, or ConBee coordinator problem"
            ),
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
        if result.detail:
            prefix = "  -> " if not result.ok else "     "
            print(f"{prefix}{result.detail}")

    print("=" * 72)
    overall = all(result.ok for result in results)
    print(f"OVERALL: {'OK' if overall else 'NOT OK'}")


def main() -> int:
    results = collect_results()
    print_report(results)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
