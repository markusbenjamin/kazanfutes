"""Log a five-minute battery-health snapshot for every IKEA PARASOLL sensor."""

from __future__ import annotations

from typing import Any, Iterable

from utils.device_watchdog import battery_observation
from utils.project import ModuleException, ServiceException, log, log_data, read_deconz_state, report


LOG_PATH = "zigbee/parasoll_batteries.json"


def is_parasoll(raw: dict[str, Any]) -> bool:
    return (
        str(raw.get("manufacturername", "")).casefold() == "ikea of sweden"
        and "parasoll" in str(raw.get("modelid", "")).casefold()
    )


def _physical_id(raw: dict[str, Any], fallback: str) -> str:
    unique_id = raw.get("uniqueid")
    return str(unique_id).split("-", 1)[0].lower() if unique_id else fallback


def _minimum_numeric(values: list[Any]) -> float | None:
    numeric: list[float] = []
    for value in values:
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    return min(numeric) if numeric else None


def parasoll_battery_snapshot(raw_devices: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize one battery observation per physical Parasoll device."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, raw in enumerate(raw_devices):
        if is_parasoll(raw):
            groups.setdefault(_physical_id(raw, f"parasoll_{index}"), []).append(raw)

    devices: list[dict[str, Any]] = []
    for physical_id, raws in sorted(groups.items()):
        batteries = [(raw.get("config") or {}).get("battery", (raw.get("state") or {}).get("battery")) for raw in raws]
        raw_battery = _minimum_numeric(batteries)
        low_battery = any((raw.get("state") or {}).get("lowbattery") is True for raw in raws)
        reachable_values = [
            (raw.get("config") or {}).get("reachable", (raw.get("state") or {}).get("reachable"))
            for raw in raws
        ]
        known_reachability = [value for value in reachable_values if isinstance(value, bool)]
        last_seen = [str(raw["lastseen"]) for raw in raws if raw.get("lastseen")]
        names = sorted({str(raw["name"]) for raw in raws if raw.get("name")})
        devices.append({
            "device_id": f"zigbee:{physical_id}",
            "name": names[0] if names else f"Parasoll {physical_id}",
            "names": names,
            "resources": len(raws),
            "battery": battery_observation(
                raw_battery,
                low_battery,
                configured_scale="unknown",
                zero_is_unknown=True,
            ),
            "reachable": True if any(known_reachability) else (False if known_reachability else None),
            "last_seen_at": max(last_seen) if last_seen else None,
        })
    return devices


def collect_snapshot() -> list[dict[str, Any]]:
    session = read_deconz_state()
    return parasoll_battery_snapshot(device.raw for device in session.sensors.values())


def main() -> int:
    success = False
    try:
        devices = collect_snapshot()
        if not devices:
            raise RuntimeError("No IKEA PARASOLL sensors found in deCONZ")
        log_data({"devices": devices}, LOG_PATH)
        report(f"Logged battery state for {len(devices)} Parasoll sensors.", verbose=True)
        success = True
    except ModuleException as error:
        ServiceException("Could not log Parasoll battery states", original_exception=error, severity=2)
    except Exception:
        ServiceException("Could not log Parasoll battery states", severity=2)
    log({"success": success})
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
