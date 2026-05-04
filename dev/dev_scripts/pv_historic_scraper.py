import json
import time
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# -------------------------
# config
# -------------------------

LOGIN_URL = "https://eu5.fusionsolar.huawei.com/unisso/login.action?"
TREND_URL = (
    "https://uni004eu5.fusionsolar.huawei.com/"
    "uniportal/pvmswebsite/assets/build/cloud.html"
    "?app-id=smartpvms&instance-id=smartpvms"
    "&zone-id=region-4-c697c8a6-f0e6-42b9-ba57-65f4075b39d4"
    "#/view/station/NE=146835908/station-trend-analysis/"
)

ACCESS_PATH = Path(
    r"C:\Users\Beno\Documents\SZAKI\dev\kazanfutes\config\secrets_and_env\fusionsolar_access.json"
)

HEADLESS = True

STATION_DN = "NE=146835908"
DEVICE_DN = "NE=146835906"
DEVICE_DN_ID = "107977377"

# "historical" or "live"
MODE = "live"

# historical mode only; ignored in live mode
START_DATE = "2026-01-01"
END_DATE = "2026-04-30"

# available inverter dimensions from the signal tree:
#
# AC-side voltages / currents / power / frequency
#   30004  -> "Phase A voltage(V)"
#   30005  -> "Phase B voltage(V)"
#   30006  -> "Phase C voltage(V)"
#   30007  -> "Grid current/Grid phase A current(A)"
#   30008  -> "Phase B current(A)"
#   30009  -> "Phase C current(A)"
#   30012  -> "Power factor"
#   30013  -> "Grid frequency(Hz)"
#   30014  -> "Active power(kW)"
#   30015  -> "Output reactive power(kvar)"
#   30016  -> "Daily energy(kWh)"
#   30017  -> "Total input power(kW)"
#
# PV input channels
#   31001  -> "PV1 input voltage(V)"
#   31002  -> "PV1 input current(A)"
#   31004  -> "PV2 input voltage(V)"
#   31005  -> "PV2 input current(A)"
#   31007  -> "PV3 input voltage(V)"
#   31008  -> "PV3 input current(A)"
#   31010  -> "PV4 input voltage(V)"
#   31011  -> "PV4 input current(A)"
#   31013  -> "PV5 input voltage(V)"
#   31014  -> "PV5 input current(A)"
#   31016  -> "PV6 input voltage(V)"
#   31017  -> "PV6 input current(A)"
#   31019  -> "PV7 input voltage(V)"
#   31020  -> "PV7 input current(A)"
#   31022  -> "PV8 input voltage(V)"
#   31023  -> "PV8 input current(A)"
#
# MPPT cumulative energies
#   32001  -> "MPPT 1 DC cumulative energy(kWh)"
#   32002  -> "MPPT 2 DC cumulative energy(kWh)"
#   32003  -> "MPPT 3 DC cumulative energy(kWh)"
#   32004  -> "MPPT 4 DC cumulative energy(kWh)"
#
# DIMENSIONS is ignored when ALL_DIMENSIONS = True
DIMENSIONS = [30014]

# fetch every inverter signal exposed by the signal tree
ALL_DIMENSIONS = True

# today's data is just one day, so this can stay as is
SIGNAL_BATCH_SIZE = 8

KEEP_RAW_BLOCKS = False

OUT_PATH = Path("fusionsolar_data_today.json")
DEBUG_SCREENSHOT_PATH = Path("fusionsolar_debug.png")


# -------------------------
# helpers
# -------------------------

def fail(page, msg):
    try:
        DEBUG_SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
    except Exception:
        pass
    raise RuntimeError(msg)


def load_credentials():
    with ACCESS_PATH.open("r", encoding="utf-8") as f:
        creds = json.load(f)
    return creds["username"], creds["password"]


def parse_ymd(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def first_of_next_month(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def month_chunks(start_date_str, end_date_str):
    start = parse_ymd(start_date_str)
    end = parse_ymd(end_date_str)
    if end < start:
        raise ValueError("END_DATE must be >= START_DATE")

    chunks = []
    cur = start
    while cur <= end:
        nxt = first_of_next_month(cur)
        chunk_end = min(end, nxt - timedelta(days=1))
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = nxt
    return chunks


def batched(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def normalize_dimension_selection(signal_map, dimensions, all_dimensions):
    if all_dimensions:
        return sorted(int(k) for k in signal_map.keys())

    label_to_id = {v["label"]: int(k) for k, v in signal_map.items()}

    out = []
    for dim in dimensions:
        if isinstance(dim, int):
            key = str(dim)
            if key not in signal_map:
                raise KeyError(f"signal id not found in signal map: {dim}")
            out.append(dim)
        elif isinstance(dim, str):
            if dim.isdigit():
                if dim not in signal_map:
                    raise KeyError(f"signal id not found in signal map: {dim}")
                out.append(int(dim))
            else:
                if dim not in label_to_id:
                    raise KeyError(f"signal label not found in signal map: {dim}")
                out.append(label_to_id[dim])
        else:
            raise TypeError(f"unsupported dimension selector: {dim!r}")

    seen = set()
    deduped = []
    for x in out:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped


def clean_counter_value(v):
    if isinstance(v, (int, float)) and abs(v) > 1e300:
        return None
    return v


def build_signal_filters(signal_ids):
    return [
        {
            "signalId": sid,
            "deviceDnId": DEVICE_DN_ID,
            "stationDn": STATION_DN,
        }
        for sid in signal_ids
    ]


# -------------------------
# main
# -------------------------

USERNAME, PASSWORD = load_credentials()

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
        # -------------------------
        # login
        # -------------------------
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

        page.wait_for_selector("#username", timeout=15000)
        page.wait_for_selector("#value", timeout=15000)
        page.wait_for_selector("#btn_outerverify", timeout=15000)

        page.locator("#username").fill(USERNAME)
        page.locator("#value").fill(PASSWORD)
        page.locator("#btn_outerverify").click()

        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(3)

        if page.locator("#username").count() > 0 and page.locator("#btn_outerverify").count() > 0:
            fail(page, "Still on login page after submit")

        # -------------------------
        # trend page
        # -------------------------
        page.goto(TREND_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(5)

        if not seen["roarand"]:
            fail(page, "Did not capture roarand from page traffic")

        # -------------------------
        # signal tree / signal map
        # -------------------------
        signal_tree_result = page.evaluate(
            """
            async ({ deviceDn, roarand }) => {
                const r = await fetch(
                    `/rest/dp/pvms/plant/v1/energy-analyzer/device-tree?parentDn=${encodeURIComponent(deviceDn)}&treeDepth=signal&_=${Date.now()}`,
                    {
                        method: "GET",
                        headers: {
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                            "X-Requested-With": "XMLHttpRequest",
                            "x-non-renewal-session": "true",
                            "x-timezone-offset": String(-new Date().getTimezoneOffset()),
                            "roarand": roarand
                        }
                    }
                );

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
            {"deviceDn": DEVICE_DN, "roarand": seen["roarand"]},
        )

        if signal_tree_result["status"] != 200 or not signal_tree_result["json"]:
            fail(page, f"Could not fetch signal tree: {signal_tree_result}")

        raw_tree = signal_tree_result["json"]
        signal_map = {}

        def walk(node):
            if not isinstance(node, dict):
                return
            if node.get("isSign") and node.get("mocId") is not None:
                signal_map[str(node["mocId"])] = {
                    "label": node.get("nodeName"),
                    "unit": node.get("unit"),
                    "elementId": node.get("elementId"),
                    "elementDn": node.get("elementDn"),
                    "parentDn": node.get("parentDn"),
                }
            for child in node.get("childList", []) or []:
                walk(child)

        walk(raw_tree)

        if not signal_map:
            fail(page, "Signal map came back empty")

        selected_signal_ids = normalize_dimension_selection(
            signal_map=signal_map,
            dimensions=DIMENSIONS,
            all_dimensions=ALL_DIMENSIONS,
        )

        # -------------------------
        # time range
        # -------------------------
        if MODE == "live":
            today = datetime.now().date().isoformat()
            time_chunks = [(today, today)]
        elif MODE == "historical":
            time_chunks = month_chunks(START_DATE, END_DATE)
        else:
            raise ValueError(f"Unsupported MODE: {MODE}")

        signal_batches = list(batched(selected_signal_ids, SIGNAL_BATCH_SIZE))

        # -------------------------
        # request history in chunks
        # -------------------------
        raw_blocks = []
        request_log = []
        history_timezone_name = None

        series_by_signal = {
            sid: {
                "deviceDnId": int(DEVICE_DN_ID),
                "signalId": sid,
                "label": signal_map[str(sid)]["label"],
                "unit": signal_map[str(sid)]["unit"],
                "points": [],
            }
            for sid in selected_signal_ids
        }

        for chunk_start, chunk_end in time_chunks:
            for signal_batch in signal_batches:
                body = {
                    "startTime": chunk_start,
                    "stationDn": STATION_DN,
                    "endTime": chunk_end,
                    "signalFilters": build_signal_filters(signal_batch),
                }

                history_result = page.evaluate(
                    """
                    async ({ body, roarand }) => {
                        const r = await fetch("/rest/dp/pvms/plant/v1/energy-analyzer/device-history-data", {
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
                    {"body": body, "roarand": seen["roarand"]},
                )

                request_log.append({
                    "chunkStart": chunk_start,
                    "chunkEnd": chunk_end,
                    "signalIds": signal_batch,
                    "status": history_result["status"],
                })

                if history_result["status"] != 200 or not history_result["json"]:
                    fail(
                        page,
                        f"History request failed for {chunk_start}..{chunk_end}, "
                        f"signals={signal_batch}: {history_result}"
                    )

                history_json = history_result["json"]

                if history_timezone_name is None:
                    history_timezone_name = history_json.get("timeZone", "UTC")

                if KEEP_RAW_BLOCKS:
                    raw_blocks.append({
                        "chunkStart": chunk_start,
                        "chunkEnd": chunk_end,
                        "signalIds": signal_batch,
                        "response": history_json,
                    })

                for device_block in history_json.get("data", []):
                    for signal_block in device_block.get("signalData", []):
                        sid = signal_block.get("signalId")
                        if sid not in series_by_signal:
                            continue
                        series_by_signal[sid]["deviceDnId"] = device_block.get("deviceDnId")
                        for point in signal_block.get("pmDataList", []):
                            series_by_signal[sid]["points"].append({
                                "timestampEpochS": point["startTime"],
                                "value": clean_counter_value(point.get("counterValue")),
                            })

                # -------------------------
        # post-process / trim live / sort / deduplicate / timestamp strings
        # -------------------------
        tz_name = history_timezone_name or "UTC"
        tz = ZoneInfo(tz_name)
        now_local = datetime.now(tz)

        final_series = []
        for sid in selected_signal_ids:
            s = series_by_signal[sid]

            dedup = {}
            for point in s["points"]:
                epoch_s = point["timestampEpochS"]
                dt_local = datetime.fromtimestamp(epoch_s, tz=timezone.utc).astimezone(tz)

                if MODE == "live" and dt_local > now_local:
                    continue

                dedup[epoch_s] = {
                    "timestamp": dt_local.isoformat(),
                    "value": point["value"],
                }

            ordered_points = [dedup[k] for k in sorted(dedup.keys())]

            final_series.append({
                "deviceDnId": s["deviceDnId"],
                "signalId": s["signalId"],
                "label": s["label"],
                "unit": s["unit"],
                "points": ordered_points,
            })

        if MODE == "live":
            # build one timestamp-indexed table
            rows_by_ts = {}

            for s in final_series:
                label = s["label"]
                for p in s["points"]:
                    ts = p["timestamp"]
                    rows_by_ts.setdefault(ts, {})
                    rows_by_ts[ts][label] = p["value"]

            if not rows_by_ts:
                raise RuntimeError("No live data points found")

            # pick the latest timestamp that has at least one real value
            usable_timestamps = [
                ts
                for ts, row in rows_by_ts.items()
                if any(v is not None for v in row.values())
            ]

            if not usable_timestamps:
                raise RuntimeError("Live data contains only missing values")

            latest_ts = max(usable_timestamps)
            latest_row = rows_by_ts[latest_ts]

            # print only signal names and values; no metadata
            for sid in selected_signal_ids:
                label = signal_map[str(sid)]["label"]
                print(f"{label}: {latest_row.get(label)}")
        else:
            output = {
                "meta": {
                    "mode": MODE,
                    "headless": HEADLESS,
                    "stationDn": STATION_DN,
                    "deviceDn": DEVICE_DN,
                    "deviceDnId": DEVICE_DN_ID,
                    "startDate": time_chunks[0][0],
                    "endDate": time_chunks[-1][1],
                    "allDimensions": ALL_DIMENSIONS,
                    "requestedDimensions": DIMENSIONS,
                    "resolvedSignalIds": selected_signal_ids,
                    "signalBatchSize": SIGNAL_BATCH_SIZE,
                    "timeChunks": time_chunks,
                    "timeZone": tz_name,
                },
                "signalMap": signal_map,
                "requestLog": request_log,
                "series": final_series,
            }

            if KEEP_RAW_BLOCKS:
                output["rawBlocks"] = raw_blocks

            OUT_PATH.write_text(
                json.dumps(output, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            print("saved:", OUT_PATH)
            print("mode:", MODE)
            print("signals fetched:", len(final_series))
            print("time chunks:", len(time_chunks))
            print("signal batches:", len(signal_batches))
            for s in final_series[:10]:
                print(f"{s['signalId']:>5} | {s['label']} | {len(s['points'])} points")

    except PlaywrightTimeoutError as e:
        fail(page, f"Playwright timeout: {e}")
    finally:
        browser.close()