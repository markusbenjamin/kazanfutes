"""
Logs one FusionSolar live inverter sample.
"""

from utils.project import *
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import os
import re
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOGIN_URL = "https://eu5.fusionsolar.huawei.com/unisso/login.action?"
TREND_URL = (
    "https://uni004eu5.fusionsolar.huawei.com/"
    "uniportal/pvmswebsite/assets/build/cloud.html"
    "?app-id=smartpvms&instance-id=smartpvms"
    "&zone-id=region-4-c697c8a6-f0e6-42b9-ba57-65f4075b39d4"
    "#/view/station/NE=146835908/station-trend-analysis/"
)

ACCESS_PATH = os.path.join(get_project_root(), 'config', 'secrets_and_env', 'fusionsolar_access.json')

STATION_DN = "NE=146835908"
DEVICE_DN = "NE=146835906"
DEVICE_DN_ID = "107977377"

CHROMIUM_BIN = "/usr/bin/chromium"
CHROMEDRIVER_BIN = "/usr/bin/chromedriver"

HEADLESS = True
SIGNAL_BATCH_SIZE = 8


def load_credentials():
    with open(ACCESS_PATH, "r", encoding="utf-8") as f:
        creds = json.load(f)
    return creds["username"], creds["password"]


def batched(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def clean_counter_value(v):
    if isinstance(v, (int, float)) and abs(v) > 1e300:
        return None
    return v


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

        wait.until(EC.presence_of_element_located((By.ID, "username")))
        wait.until(EC.presence_of_element_located((By.ID, "value")))
        wait.until(EC.presence_of_element_located((By.ID, "btn_outerverify")))

        driver.find_element(By.ID, "username").send_keys(username)
        driver.find_element(By.ID, "value").send_keys(password)
        driver.find_element(By.ID, "btn_outerverify").click()

        time.sleep(5)

        if driver.find_elements(By.ID, "username") and driver.find_elements(By.ID, "btn_outerverify"):
            raise RuntimeError("Still on login page after submit")

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
            raise RuntimeError("Did not capture roarand from browser traffic")

        signal_tree_result = fetch_json(
            driver=driver,
            url=f"/rest/dp/pvms/plant/v1/energy-analyzer/device-tree?parentDn={DEVICE_DN}&treeDepth=signal&_={int(time.time() * 1000)}",
            roarand=roarand,
        )

        if signal_tree_result["status"] != 200 or not signal_tree_result["json"]:
            raise RuntimeError(f"Could not fetch signal tree: {signal_tree_result}")

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
                raise RuntimeError(f"History request failed: {history_result}")

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
            raise RuntimeError("Live data contains only missing values")

        latest_epoch = max(usable_epochs)
        latest_row = rows_by_epoch[latest_epoch]

        out = {"timestamp": timestamp()}
        for sid in signal_ids:
            label = signal_map[sid]["label"]
            out[label_to_key(label)] = latest_row.get(label)

        return out

    finally:
        driver.quit()


success = False

#try:
out = read_live_row()
#log_data(out, "electricity/pv_inverter.json")
print(out)
#report(json.dumps(out, ensure_ascii=False))
success = True

'''
except ModuleException as e:
    ServiceException(
        "Module error while trying to read and log FusionSolar inverter data",
        original_exception=e,
        severity=2
    )

except Exception:
    ServiceException(
        "Unexpected error while trying to read and log FusionSolar inverter data",
        severity=2
    )
'''

# Log execution
#log({"success": success})