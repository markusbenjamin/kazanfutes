"""
Logs one FusionSolar live inverter sample.
"""

from utils.project import *
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import math
import os
import re
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementNotInteractableException

LOGIN_URL = "https://eu5.fusionsolar.huawei.com/unisso/login.action?"
TREND_URL = (
    "https://uni004eu5.fusionsolar.huawei.com/"
    "uniportal/pvmswebsite/assets/build/cloud.html"
    "?app-id=smartpvms&instance-id=smartpvms"
    "&zone-id=region-4-c697c8a6-f0e6-42b9-ba57-65f4075b39d4"
    "#/view/station/NE=146835908/station-trend-analysis/"
)

ACCESS_PATH = os.path.join(
    get_project_root(),
    "config",
    "secrets_and_env",
    "fusionsolar_access.json",
)

STATION_DN = "NE=146835908"
DEVICE_DN = "NE=146835906"
DEVICE_DN_ID = "107977377"

CHROMIUM_BIN = "/usr/bin/chromium"
CHROMEDRIVER_BIN = "/usr/bin/chromedriver"

HEADLESS = True
SIGNAL_BATCH_SIZE = 8
PV_STATUS_LOG_PATH = "electricity/pv_inverter_status.json"
ZERO_VOLTAGE_THRESHOLD_VOLTS = 0.001


class PVObservationError(RuntimeError):
    """A FusionSolar observation failure with its observable scope."""

    def __init__(self, stage, access_state, message):
        super().__init__(message)
        self.stage = stage
        self.access_state = access_state


def load_credentials():
    with open(ACCESS_PATH, "r", encoding="utf-8") as f:
        creds = json.load(f)
    return creds["username"], creds["password"]


def batched(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def clean_counter_value(v):
    if isinstance(v, (int, float)) and abs(v) > 1e300:
        return None
    return v


def finite_number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def inverter_observation_status(row):
    """Describe what the logger directly observed, without inferring sunlight."""
    voltages = [
        value
        for key, raw_value in row.items()
        if re.fullmatch(r"pv\d+_input_voltage_v", key)
        for value in [finite_number(raw_value)]
        if value is not None
    ]
    active_power = finite_number(row.get("active_power_kw"))
    if not voltages:
        voltage_state = "unknown"
    elif all(abs(value) <= ZERO_VOLTAGE_THRESHOLD_VOLTS for value in voltages):
        voltage_state = "all_zero"
    elif any(abs(value) <= ZERO_VOLTAGE_THRESHOLD_VOLTS for value in voltages):
        voltage_state = "partially_zero"
    else:
        voltage_state = "nonzero"

    return {
        "timestamp": timestamp(),
        "access_state": "reachable",
        "telemetry_state": "received",
        "source_timestamp": row.get("source_timestamp"),
        "dc_voltage_state": voltage_state,
        "dc_voltage_field_count": len(voltages),
        "active_power_state": (
            "unknown" if active_power is None
            else "zero" if abs(active_power) <= ZERO_VOLTAGE_THRESHOLD_VOLTS
            else "nonzero"
        ),
    }


def failed_observation_status(error):
    access_state = getattr(error, "access_state", "unavailable")
    telemetry_state = "missing" if access_state == "reachable" else "unknown"
    return {
        "timestamp": timestamp(),
        "access_state": access_state,
        "telemetry_state": telemetry_state,
        "failure_stage": getattr(error, "stage", "unknown"),
        "error_type": type(error).__name__,
    }


def log_observation_status(status):
    log_data(status, PV_STATUS_LOG_PATH)


def label_to_key(label):
    s = label.lower()
    s = s.replace("/", " ")
    s = re.sub(r"[()]", " ", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def build_signal_filters(signal_ids):
    return [
        {
            "signalId": sid,
            "deviceDnId": DEVICE_DN_ID,
            "stationDn": STATION_DN,
        }
        for sid in signal_ids
    ]


def make_driver():
    opts = Options()
    opts.binary_location = CHROMIUM_BIN

    if HEADLESS:
        opts.add_argument("--headless=new")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")

    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(executable_path=CHROMEDRIVER_BIN)
    return webdriver.Chrome(service=service, options=opts)


def set_input_value(driver, element, value):
    driver.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];
        el.focus();
        el.value = "";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        """,
        element,
        value,
    )


def extract_roarand_from_performance_logs(driver):
    try:
        logs = driver.get_log("performance")
    except Exception:
        return None

    for entry in reversed(logs):
        try:
            msg = json.loads(entry["message"])["message"]
        except Exception:
            continue

        method = msg.get("method")
        params = msg.get("params", {})
        headers = None

        if method == "Network.requestWillBeSentExtraInfo":
            headers = params.get("headers", {})
        elif method == "Network.requestWillBeSent":
            headers = params.get("request", {}).get("headers", {})

        if not headers:
            continue

        for k, v in headers.items():
            if str(k).lower() == "roarand":
                return v

    return None


def fetch_json(driver, url, roarand):
    return driver.execute_async_script(
        """
        const url = arguments[0];
        const roarand = arguments[1];
        const done = arguments[arguments.length - 1];

        fetch(url, {
            method: "GET",
            headers: {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "x-non-renewal-session": "true",
                "x-timezone-offset": String(-new Date().getTimezoneOffset()),
                "roarand": roarand
            }
        })
        .then(async (r) => {
            const text = await r.text();
            let json = null;
            try { json = JSON.parse(text); } catch {}
            done({
                status: r.status,
                json: json,
                text: json ? null : text
            });
        })
        .catch((e) => done({
            status: null,
            json: null,
            text: String(e)
        }));
        """,
        url,
        roarand,
    )


def post_json(driver, url, body, roarand):
    return driver.execute_async_script(
        """
        const url = arguments[0];
        const body = arguments[1];
        const roarand = arguments[2];
        const done = arguments[arguments.length - 1];

        fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "x-non-renewal-session": "true",
                "x-timezone-offset": String(-new Date().getTimezoneOffset()),
                "roarand": roarand
            },
            body: JSON.stringify(body)
        })
        .then(async (r) => {
            const text = await r.text();
            let json = null;
            try { json = JSON.parse(text); } catch {}
            done({
                status: r.status,
                json: json,
                text: json ? null : text
            });
        })
        .catch((e) => done({
            status: null,
            json: null,
            text: String(e)
        }));
        """,
        url,
        body,
        roarand,
    )


def read_live_row():
    username, password = load_credentials()
    driver = make_driver()
    wait = WebDriverWait(driver, 30)

    try:
        driver.get(LOGIN_URL)

        wait.until(EC.visibility_of_element_located((By.ID, "username")))
        wait.until(EC.visibility_of_element_located((By.ID, "value")))
        wait.until(EC.element_to_be_clickable((By.ID, "btn_outerverify")))

        username_el = driver.find_element(By.ID, "username")
        password_el = driver.find_element(By.ID, "value")
        login_btn = driver.find_element(By.ID, "btn_outerverify")

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", username_el)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", password_el)
        time.sleep(0.5)

        try:
            username_el.click()
            username_el.clear()
            username_el.send_keys(username)

            password_el.click()
            password_el.clear()
            password_el.send_keys(password)
        except ElementNotInteractableException:
            set_input_value(driver, username_el, username)
            set_input_value(driver, password_el, password)

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", login_btn)
        time.sleep(0.3)

        try:
            login_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", login_btn)

        time.sleep(5)

        if driver.find_elements(By.ID, "username") and driver.find_elements(By.ID, "btn_outerverify"):
            raise PVObservationError("login", "unavailable", "Still on login page after submit")

        try:
            driver.get_log("performance")
        except Exception:
            pass

        driver.get(TREND_URL)
        time.sleep(6)

        roarand = extract_roarand_from_performance_logs(driver)
        if not roarand:
            driver.refresh()
            time.sleep(6)
            roarand = extract_roarand_from_performance_logs(driver)

        if not roarand:
            raise PVObservationError("session", "unavailable", "Did not capture roarand from browser traffic")

        signal_tree_result = fetch_json(
            driver=driver,
            url=f"/rest/dp/pvms/plant/v1/energy-analyzer/device-tree?parentDn={DEVICE_DN}&treeDepth=signal&_={int(time.time() * 1000)}",
            roarand=roarand,
        )

        if signal_tree_result["status"] != 200 or not signal_tree_result["json"]:
            raise PVObservationError("signal_tree", "unavailable", "Could not fetch signal tree")

        signal_map = {}

        def walk(node):
            if not isinstance(node, dict):
                return
            if node.get("isSign") and node.get("mocId") is not None:
                signal_map[int(node["mocId"])] = {
                    "label": node.get("nodeName"),
                    "unit": node.get("unit"),
                }
            for child in node.get("childList", []) or []:
                walk(child)

        walk(signal_tree_result["json"])

        signal_ids = sorted(signal_map.keys())
        today = datetime.now().date().isoformat()

        series_by_signal = {
            sid: {
                "label": signal_map[sid]["label"],
                "points": [],
            }
            for sid in signal_ids
        }

        history_url = "/rest/dp/pvms/plant/v1/energy-analyzer/device-history-data"

        for signal_batch in batched(signal_ids, SIGNAL_BATCH_SIZE):
            body = {
                "startTime": today,
                "stationDn": STATION_DN,
                "endTime": today,
                "signalFilters": build_signal_filters(signal_batch),
            }

            history_result = post_json(
                driver=driver,
                url=history_url,
                body=body,
                roarand=roarand,
            )

            if history_result["status"] != 200 or not history_result["json"]:
                raise PVObservationError("history", "unavailable", "History request failed")

            history_json = history_result["json"]
            tz = ZoneInfo(history_json.get("timeZone", "UTC"))
            now_local = datetime.now(tz)

            for device_block in history_json.get("data", []):
                for signal_block in device_block.get("signalData", []):
                    sid = signal_block.get("signalId")
                    if sid not in series_by_signal:
                        continue
                    for point in signal_block.get("pmDataList", []):
                        epoch_s = point["startTime"]
                        dt_local = datetime.fromtimestamp(epoch_s, tz=timezone.utc).astimezone(tz)
                        if dt_local > now_local:
                            continue
                        series_by_signal[sid]["points"].append({
                            "epoch": epoch_s,
                            "value": clean_counter_value(point.get("counterValue")),
                        })

        rows_by_epoch = {}
        for sid, s in series_by_signal.items():
            label = s["label"]
            for point in s["points"]:
                epoch = point["epoch"]
                rows_by_epoch.setdefault(epoch, {})
                rows_by_epoch[epoch][label] = point["value"]

        usable_epochs = [
            epoch
            for epoch, row in rows_by_epoch.items()
            if any(v is not None for v in row.values())
        ]

        if not usable_epochs:
            raise PVObservationError("history", "reachable", "Live data contains only missing values")

        latest_epoch = max(usable_epochs)
        latest_row = rows_by_epoch[latest_epoch]

        out = {
            "timestamp": timestamp(),
            "source_timestamp": datetime.fromtimestamp(
                latest_epoch,
                tz=timezone.utc,
            ).astimezone(tz).isoformat(timespec="seconds"),
        }
        for sid in signal_ids:
            label = signal_map[sid]["label"]
            out[label_to_key(label)] = latest_row.get(label)

        return out

    finally:
        driver.quit()


def main():
    try:
        out = read_live_row()
    except Exception as error:
        try:
            log_observation_status(failed_observation_status(error))
        except Exception:
            pass
        if isinstance(error, ModuleException):
            ServiceException(
                "Module error while trying to read FusionSolar inverter data",
                original_exception=error,
                severity=2,
            )
        else:
            ServiceException(
                "FusionSolar inverter is unavailable to the logger",
                severity=2,
            )
        return False

    try:
        log_data(out, "electricity/pv_inverter.json")
        log_observation_status(inverter_observation_status(out))
    except Exception as error:
        ServiceException(
            "FusionSolar inverter data was read but could not be logged",
            original_exception=error if isinstance(error, ModuleException) else None,
            severity=2,
        )
        return False

    report(json.dumps(out, ensure_ascii=False))
    return True


success = False


if __name__ == "__main__":
    success = main()
    log({"success": success})
    if not success:
        raise SystemExit(1)
