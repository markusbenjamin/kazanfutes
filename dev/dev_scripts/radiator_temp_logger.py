from utils.project import *

#region Shelly peripheral temperatures

def shelly_rpc(ip:str, method:str, params:dict = None, timeout:float = 5.0):
    """
    Generic Shelly RPC call wrapper.
    Returns the actual payload body regardless of whether the device replies
    with bare JSON, {"result": ...}, or {"params": ...}.
    """
    try:
        url = f"http://{ip}/rpc"
        payload = {
            "id": 1,
            "method": method,
            "params": {} if params is None else params
        }

        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            if "error" in data:
                raise ModuleException(f"Shelly RPC {method} failed on {ip}: {data['error']}")
            if "result" in data:
                return data["result"]
            if "params" in data:
                return data["params"]

        return data

    except ModuleException:
        raise
    except Exception as e:
        raise ModuleException(f"couldn't call Shelly RPC {method} on {ip}: {e}")

def get_radiator_temps(shelly_ips:dict, timeout:float = 5.0, verbose:bool = False, detailed:bool = False):
    """
    Read all configured DS18B20 peripheral temperatures from multiple Shelly devices.

    If detailed = True, return the full structured output.
    If detailed = False, return just the temperatures.
    """
    try:
        if detailed:
            out = {
                "timestamp": timestamp(),
                "devices": {}
            }
        else:
            out = {}

        for device_name, ip in shelly_ips.items():
            report(f"reading Shelly peripherals from {device_name} at {ip}", verbose=verbose)

            try:
                peripherals = shelly_rpc(ip, "SensorAddon.GetPeripherals", timeout=timeout)
                ds18b20 = peripherals.get("ds18b20", {}) if isinstance(peripherals, dict) else {}

                if detailed:
                    device_out = {
                        "ip": ip,
                        "peripherals": {}
                    }
                else:
                    device_out = {}

                for component_key, attrs in ds18b20.items():
                    try:
                        component_type, component_id = component_key.split(":")
                        component_id = int(component_id)

                        if component_type != "temperature":
                            continue

                        status = shelly_rpc(
                            ip,
                            "Temperature.GetStatus",
                            {"id": component_id},
                            timeout=timeout
                        )

                        config = shelly_rpc(
                            ip,
                            "Temperature.GetConfig",
                            {"id": component_id},
                            timeout=timeout
                        )

                        peripheral_name = config.get("name") or component_key
                        temp = status.get("tC")

                        if detailed:
                            device_out["peripherals"][peripheral_name] = {
                                "temp": temp,
                                "component": component_key,
                                "addr": attrs.get("addr"),
                                "errors": status.get("errors", [])
                            }
                        else:
                            device_out[peripheral_name] = temp

                    except Exception as e:
                        if detailed:
                            device_out["peripherals"][component_key] = {
                                "temp": None,
                                "component": component_key,
                                "addr": attrs.get("addr") if isinstance(attrs, dict) else None,
                                "errors": [str(e)]
                            }
                        else:
                            device_out[component_key] = None

                if detailed:
                    out["devices"][device_name] = device_out
                else:
                    out[device_name] = device_out

            except Exception as e:
                if detailed:
                    out["devices"][device_name] = {
                        "ip": ip,
                        "peripherals": {},
                        "error": str(e)
                    }
                else:
                    out[device_name] = {}

        return out

    except ModuleException:
        raise ModuleException("couldn't read radiator temperatures", severity=2)
    except Exception as e:
        raise ModuleException(f"unexpected error while reading radiator temperatures: {e}", severity=2)
#endregion

SHELLY_IPS = {
    "golya_radiatorok_shelly": "192.168.101.26",
    "szgk_radiator_shelly": "192.168.101.28",
    "pk_radiatorok_shelly": "192.168.101.29",
    "oktopusz_1_radiator_shelly": "192.168.101.21",
    "oktopusz_2_radiator_shelly": "192.168.101.83",
    "gep_radiator_shelly": "192.168.101.42",
    "merce_radiatorok_1_shelly": "192.168.101.37",
    "merce_radiatorok_2_shelly": "192.168.101.94",
    "ovi_radiatorok_shelly": "192.168.101.47",
    "studio_radiator_shelly": "192.168.101.74",
}

temps = get_radiator_temps(SHELLY_IPS)
report(json.dumps(temps, indent=4, ensure_ascii=False))