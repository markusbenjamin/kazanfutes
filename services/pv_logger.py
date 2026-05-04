"""
Logs one FusionSolar live inverter sample.
"""

from utils.project import *
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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

HEADLESS = True
SIGNAL_BATCH_SIZE = 8


def load_credentials():
    with ACCESS_PATH.open("r", encoding="utf-8") as f:
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


def fetch_json(page, url, roarand):
    return page.evaluate(
        """
        async ({ url, roarand }) => {
            const r = await fetch(url, {
                method: "GET",
                headers: {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "x-non-renewal-session": "true",
                    "x-timezone-offset": String(-new Date().getTimezoneOffset()),
                    "roarand": roarand
                }
            });

            const text = await r.text();
            let json = null;
            try { json = JSON.parse(text); } catch {}

            return {
                status: r.status,
                json,
                text: json ? null : text
            };
        }
        """,
        {"url": url, "roarand": roarand},
    )


def post_json(page, url, body, roarand):
    return page.evaluate(
        """
        async ({ url, body, roarand }) => {
            const r = await fetch(url, {
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
            });

            const text = await r.text();
            let json = null;
            try { json = JSON.parse(text); } catch {}

            return {
                status: r.status,
                json,
                text: json ? null : text
            };
        }
        """,
        {"url": url, "body": body, "roarand": roarand},
    )


def build_signal_filters(signal_ids):
    return [
        {
            "signalId": sid,
            "deviceDnId": DEVICE_DN_ID,
            "stationDn": STATION_DN,
        }
        for sid in signal_ids
    ]


def read_live_row():
    username, password = load_credentials()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context()
        page = context.new_page()

        seen = {"roarand": None}

        def on_request(req):
            if "/rest/" not in req.url:
                return
            roarand = req.headers.get("roarand")
            if roarand and not seen["roarand"]:
                seen["roarand"] = roarand

        page.on("request", on_request)

        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

            page.wait_for_selector("#username", timeout=15000)
            page.wait_for_selector("#value", timeout=15000)
            page.wait_for_selector("#btn_outerverify", timeout=15000)

            page.locator("#username").fill(username)
            page.locator("#value").fill(password)
            page.locator("#btn_outerverify").click()

            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(3)

            if page.locator("#username").count() > 0 and page.locator("#btn_outerverify").count() > 0:
                raise RuntimeError("Still on login page after submit")

            page.goto(TREND_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(5)

            if not seen["roarand"]:
                raise RuntimeError("Did not capture roarand from page traffic")

            signal_tree_result = fetch_json(
                page=page,
                url=f"/rest/dp/pvms/plant/v1/energy-analyzer/device-tree?parentDn={DEVICE_DN}&treeDepth=signal&_={int(time.time() * 1000)}",
                roarand=seen["roarand"],
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
                    page=page,
                    url=history_url,
                    body=body,
                    roarand=seen["roarand"],
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
            browser.close()

success = False

try:
    out = read_live_row()
    print(out)
    log_data(out, "electricity/pv_inverter.json")
    report(json.dumps(out, ensure_ascii=False))
    success = True

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

#Log execution
log({"success":success})