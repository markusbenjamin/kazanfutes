"""Discover Shelly devices by stable hardware identity instead of IPv4 address."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import ipaddress
import json
import os
import tempfile
import threading
from typing import Any

import filelock
import requests


class ShellyDiscoveryError(RuntimeError):
    """Raised when a configured Shelly cannot be resolved safely."""


def normalize_mac(value: str) -> str:
    """Return a MAC as lower-case colon-separated hex."""
    compact = "".join(ch for ch in str(value) if ch.lower() in "0123456789abcdef")
    if len(compact) != 12:
        raise ValueError(f"invalid MAC address: {value!r}")
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2)).lower()


def normalize_sensor_address(value: str) -> str:
    """Normalize the decimal-byte address returned for a DS18B20 peripheral."""
    try:
        parts = [str(int(part.strip())) for part in str(value).split(":")]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid sensor address: {value!r}") from exc
    if len(parts) != 8:
        raise ValueError(f"invalid sensor address: {value!r}")
    return ":".join(parts)


def load_shelly_config(project_root: str) -> dict[str, Any]:
    path = os.path.join(project_root, "config", "shelly_devices.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_shelly_resolver(project_root: str, config: dict[str, Any]) -> "ShellyResolver":
    discovery = config["discovery"]
    return ShellyResolver(
        networks=discovery["networks"],
        cache_path=os.path.join(project_root, discovery["cache_relative_path"]),
        probe_timeout=float(discovery.get("probe_timeout_seconds", 0.8)),
        rpc_timeout=float(discovery.get("rpc_timeout_seconds", 1.5)),
        scan_workers=int(discovery.get("scan_workers", 48)),
    )


class ShellyResolver:
    """
    Resolve logical Shelly devices without trusting a previously assigned IP.

    The resolver validates cached addresses through the unauthenticated /shelly
    identity endpoint. On a miss it performs a bounded concurrent scan of only
    the configured networks, records every Shelly's base MAC, and optionally
    matches radiator gateways by their attached DS18B20 hardware addresses.
    """

    def __init__(
        self,
        networks: list[str],
        cache_path: str,
        probe_timeout: float = 0.8,
        rpc_timeout: float = 1.5,
        scan_workers: int = 48,
    ):
        self.networks = [str(ipaddress.ip_network(network, strict=False)) for network in networks]
        self.cache_path = os.path.abspath(cache_path)
        self.probe_timeout = probe_timeout
        self.rpc_timeout = rpc_timeout
        self.scan_workers = max(1, scan_workers)
        self._thread_lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}
        self._reload_cache()

    @property
    def _cache_lock_path(self) -> str:
        return self.cache_path + ".lock"

    @property
    def _scan_lock_path(self) -> str:
        return self.cache_path + ".scan.lock"

    def _empty_cache(self) -> dict[str, Any]:
        return {"version": 1, "devices": {}, "aliases": {}}

    def _read_cache_file(self) -> dict[str, Any]:
        try:
            with open(self.cache_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                return self._empty_cache()
            data.setdefault("devices", {})
            data.setdefault("aliases", {})
            return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return self._empty_cache()

    def _reload_cache(self) -> None:
        data = self._read_cache_file()
        devices: dict[str, dict[str, Any]] = {}
        for raw_mac, record in data.get("devices", {}).items():
            try:
                mac = normalize_mac(raw_mac)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("ip"):
                devices[mac] = dict(record, mac=mac)

        aliases: dict[str, str] = {}
        for alias, raw_mac in data.get("aliases", {}).items():
            try:
                aliases[str(alias)] = normalize_mac(raw_mac)
            except ValueError:
                continue

        self._devices = devices
        self._aliases = aliases

    def _persist_cache(
        self,
        records: list[dict[str, Any]] | None = None,
        aliases: dict[str, str] | None = None,
    ) -> None:
        records = records or []
        aliases = aliases or {}
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

        with filelock.FileLock(self._cache_lock_path, timeout=30):
            data = self._read_cache_file()
            for record in records:
                mac = normalize_mac(record["mac"])
                data["devices"][mac] = dict(record, mac=mac)
            for alias, raw_mac in aliases.items():
                data["aliases"][str(alias)] = normalize_mac(raw_mac)
            data["updated_at"] = datetime.now(timezone.utc).isoformat()

            fd, temporary_path = tempfile.mkstemp(
                prefix="shelly-discovery-",
                suffix=".json",
                dir=os.path.dirname(self.cache_path),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                os.replace(temporary_path, self.cache_path)
            except Exception:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
                raise

        self._reload_cache()

    def _http_session(self) -> requests.Session:
        session = requests.Session()
        # Local device discovery must not be routed through an HTTP proxy.
        session.trust_env = False
        return session

    def _rpc(self, ip: str, method: str, params: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {"id": 1, "method": method}
        if params is not None:
            payload["params"] = params

        with self._http_session() as session:
            response = session.post(
                f"http://{ip}/rpc",
                json=payload,
                timeout=self.rpc_timeout,
            )
            response.raise_for_status()
            data = response.json()

        if isinstance(data, dict):
            if "error" in data:
                raise ShellyDiscoveryError(f"{method} failed on {ip}: {data['error']}")
            if "result" in data:
                return data["result"]
            if "params" in data:
                return data["params"]
        return data

    def _probe_ip(self, ip: str, include_sensor_addresses: bool = True) -> dict[str, Any] | None:
        try:
            with self._http_session() as session:
                response = session.get(f"http://{ip}/shelly", timeout=self.probe_timeout)
                response.raise_for_status()
                info = response.json()
            if not isinstance(info, dict) or not info.get("mac"):
                return None
            mac = normalize_mac(info["mac"])
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            return None

        record: dict[str, Any] = {
            "ip": ip,
            "mac": mac,
            "id": info.get("id"),
            "name": info.get("name"),
            "model": info.get("model"),
            "app": info.get("app"),
            "gen": info.get("gen"),
            "sensor_addon_supported": False,
            "sensor_addresses": [],
            "bthome_addresses": [],
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }

        if include_sensor_addresses:
            try:
                peripherals = self._rpc(ip, "SensorAddon.GetPeripherals")
                if isinstance(peripherals, dict):
                    record["sensor_addon_supported"] = True
                    ds18b20 = peripherals.get("ds18b20", {})
                    addresses = []
                    if isinstance(ds18b20, dict):
                        for attrs in ds18b20.values():
                            if not isinstance(attrs, dict) or not attrs.get("addr"):
                                continue
                            try:
                                addresses.append(normalize_sensor_address(attrs["addr"]))
                            except ValueError:
                                continue
                    record["sensor_addresses"] = sorted(set(addresses))
            except Exception:
                # Most Shellys do not have a Sensor Add-On. Identification by
                # their base MAC remains valid even when this optional RPC fails.
                pass

            try:
                components = self._rpc(
                    ip,
                    "Shelly.GetComponents",
                    {"dynamic_only": True, "include": ["config"]},
                )
                bthome_addresses = []
                for component in components.get("components", []):
                    if not isinstance(component, dict):
                        continue
                    address = component.get("config", {}).get("addr")
                    if not address:
                        continue
                    try:
                        bthome_addresses.append(normalize_mac(address))
                    except ValueError:
                        continue
                record["bthome_addresses"] = sorted(set(bthome_addresses))
            except Exception:
                pass

        return record

    def _candidate_ips(self) -> list[str]:
        addresses: list[str] = []
        for network_text in self.networks:
            network = ipaddress.ip_network(network_text, strict=False)
            addresses.extend(str(address) for address in network.hosts())
        return addresses

    def _scan_networks(self) -> list[dict[str, Any]]:
        addresses = self._candidate_ips()
        if not addresses:
            return []

        found: list[dict[str, Any]] = []
        worker_count = min(self.scan_workers, len(addresses))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(self._probe_ip, ip): ip for ip in addresses}
            for future in as_completed(futures):
                try:
                    record = future.result()
                except Exception:
                    record = None
                if record is not None:
                    found.append(record)

        return sorted(found, key=lambda record: ipaddress.ip_address(record["ip"]))

    def _record_matches_spec(self, record: dict[str, Any], spec: dict[str, Any]) -> bool:
        expected_names = {
            str(name).strip().casefold()
            for name in spec.get("device_names", [])
            if str(name).strip()
        }
        actual_names = {
            str(record.get(key)).strip().casefold()
            for key in ("name", "id")
            if record.get(key)
        }
        if expected_names and expected_names.intersection(actual_names):
            return True

        expected_sensors = set()
        for address in spec.get("sensor_addresses", []):
            try:
                expected_sensors.add(normalize_sensor_address(address))
            except ValueError:
                continue
        actual_sensors = set(record.get("sensor_addresses", []))
        if expected_sensors and expected_sensors.intersection(actual_sensors):
            return True

        expected_bthome = set()
        for address in spec.get("bthome_addresses", []):
            try:
                expected_bthome.add(normalize_mac(address))
            except ValueError:
                continue
        actual_bthome = set(record.get("bthome_addresses", []))
        return bool(expected_bthome and expected_bthome.intersection(actual_bthome))

    def _select_records(
        self,
        specs: dict[str, dict[str, Any]],
        records: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        selected: dict[str, dict[str, Any]] = {}
        aliases: dict[str, str] = {}
        used_macs: set[str] = set()

        for logical_name, spec in specs.items():
            raw_mac = spec.get("mac") or self._aliases.get(logical_name)
            if raw_mac:
                try:
                    mac = normalize_mac(raw_mac)
                except ValueError:
                    continue
                if mac in records and mac not in used_macs:
                    selected[logical_name] = records[mac]
                    aliases[logical_name] = mac
                    used_macs.add(mac)
                    continue

            matches = [
                record for record in records.values()
                if record["mac"] not in used_macs
                and self._record_matches_spec(record, spec)
            ]
            if len(matches) == 1:
                selected[logical_name] = matches[0]
                aliases[logical_name] = matches[0]["mac"]
                used_macs.add(matches[0]["mac"])

        return selected, aliases

    def _validate_selected(
        self,
        selected: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        validated_by_mac: dict[str, dict[str, Any] | None] = {}
        valid: dict[str, dict[str, Any]] = {}

        for logical_name, cached_record in selected.items():
            mac = normalize_mac(cached_record["mac"])
            if mac not in validated_by_mac:
                fresh = self._probe_ip(cached_record["ip"], include_sensor_addresses=False)
                validated_by_mac[mac] = fresh if fresh and fresh["mac"] == mac else None
            if validated_by_mac[mac] is not None:
                # Preserve discovered peripheral identities while refreshing
                # the current address and device metadata.
                refreshed = dict(cached_record)
                for key in ("ip", "mac", "id", "name", "model", "app", "gen", "seen_at"):
                    refreshed[key] = validated_by_mac[mac].get(key)
                valid[logical_name] = refreshed

        return valid

    def resolve_many(
        self,
        specs: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """Resolve logical names to verified device records and per-name errors."""
        with self._thread_lock:
            self._reload_cache()
            selected, aliases = self._select_records(specs, self._devices)
            resolved = self._validate_selected(selected)
            unresolved_specs = {
                name: spec for name, spec in specs.items() if name not in resolved
            }

            if unresolved_specs:
                os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                with filelock.FileLock(self._scan_lock_path, timeout=45):
                    # Another process may have completed discovery while this
                    # process waited for the scan lock.
                    self._reload_cache()
                    selected, aliases = self._select_records(specs, self._devices)
                    resolved = self._validate_selected(selected)
                    unresolved_specs = {
                        name: spec for name, spec in specs.items() if name not in resolved
                    }

                    if unresolved_specs:
                        discovered = self._scan_networks()
                        if discovered:
                            self._persist_cache(records=discovered)
                        discovered_by_mac = {
                            normalize_mac(record["mac"]): record for record in discovered
                        }
                        newly_selected, new_aliases = self._select_records(
                            unresolved_specs,
                            discovered_by_mac,
                        )
                        resolved.update(newly_selected)
                        aliases.update(new_aliases)

            if aliases:
                self._persist_cache(
                    records=list(resolved.values()),
                    aliases=aliases,
                )

            errors: dict[str, str] = {}
            for logical_name, spec in specs.items():
                if logical_name in resolved:
                    continue
                if spec.get("mac"):
                    identity = f"MAC {spec['mac']}"
                elif spec.get("sensor_addresses"):
                    identity = "configured DS18B20 address"
                elif spec.get("device_names"):
                    identity = "configured Shelly device name"
                else:
                    identity = "a stable identity"
                errors[logical_name] = (
                    f"could not find {logical_name!r} by {identity} on "
                    f"{', '.join(self.networks)}"
                )

            return resolved, errors

    def resolve_one(self, logical_name: str, spec: dict[str, Any]) -> dict[str, Any]:
        resolved, errors = self.resolve_many({logical_name: spec})
        if logical_name not in resolved:
            raise ShellyDiscoveryError(errors[logical_name])
        return resolved[logical_name]

    def discover(self, force_scan: bool = False) -> list[dict[str, Any]]:
        """Return a sorted Shelly inventory; force_scan refreshes the subnet."""
        with self._thread_lock:
            if force_scan:
                os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                with filelock.FileLock(self._scan_lock_path, timeout=45):
                    discovered = self._scan_networks()
                    if discovered:
                        self._persist_cache(records=discovered)
                    return discovered
            self._reload_cache()
            return sorted(
                self._devices.values(),
                key=lambda record: ipaddress.ip_address(record["ip"]),
            )
