from utils.project import *

WS90_BT_ADDR = "fc:4d:6a:24:64:c7"
SHELLY_IP = "192.168.101.26"

OBJ_MAP = {
    (5, 0):   "illuminance_lux",
    (32, 0):  "rain_status",
    (68, 0):  "wind_speed_m_s",
    (68, 1):  "gust_speed_m_s",
    (70, 0):  "uv_index",
    (94, 0):  "wind_direction_deg",
    (1, 0):   "battery_pct",
    (8, 0):   "dewpoint_c",
    (46, 0):  "humidity_pct",
    (69, 0):  "temperature_c",
    (95, 0):  "precipitation_mm",
    (4, 0):   "pressure_hpa",
    (12, 0):  "battery_voltage_v",
}

def _norm_mac(mac):
    return str(mac).strip().lower().replace("-", ":")

def _shelly_rpc(method, params=None, timeout=5):
    payload = {"id": 1, "method": method}
    if params is not None:
        payload["params"] = params

    try:
        response = requests.post(
            f"http://{SHELLY_IP}/rpc",
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        raise ModuleException(f"Shelly RPC failed for {method} at {SHELLY_IP}")

    if isinstance(data, dict) and "error" in data:
        raise ModuleException(f"Shelly RPC error for {method}: {data['error']}")

    return data.get("result", data)

def _get_dynamic_components():
    result = _shelly_rpc(
        "Shelly.GetComponents",
        {
            "dynamic_only": True,
            "include": ["config", "status"],
        },
        timeout=5
    )
    return result.get("components", [])

def _fallback_name(obj_id, idx):
    return f"obj_{obj_id}_idx_{idx}"

def get_weather_station_state(verbose=False):
    comps = _get_dynamic_components()
    ws90_addr = _norm_mac(WS90_BT_ADDR)

    parent = None
    readings = {}

    for comp in comps:
        key = comp.get("key", "")
        cfg = comp.get("config", {})
        st = comp.get("status", {})
        addr = _norm_mac(cfg.get("addr", ""))

        if addr != ws90_addr:
            continue

        if key.startswith("bthomedevice:"):
            parent = comp
            continue

        if not key.startswith("bthomesensor:"):
            continue

        obj_id = cfg.get("obj_id")
        idx = cfg.get("idx", 0)
        name = OBJ_MAP.get((obj_id, idx), _fallback_name(obj_id, idx))

        readings[name] = st.get("value")

    if parent is None:
        raise ModuleException(f"couldn't find WS90 parent device for {WS90_BT_ADDR}")

    pst = parent.get("status", {})
    device_last_update_ts = pst.get("last_updated_ts")

    out = {
        "timestamp": timestamp(),
        "last_updated": None if device_last_update_ts is None else datetime.fromtimestamp(
            float(device_last_update_ts),
            tz=timezone.utc
        ).astimezone(tzlocal.get_localzone()).strftime(settings["timestamp_format"]),
        "state": readings
    }

    if verbose:
        report(json.dumps(out, indent=2, ensure_ascii=False))

    return out

print(json.dumps(get_weather_station_state(verbose=False), indent=2, ensure_ascii=False))