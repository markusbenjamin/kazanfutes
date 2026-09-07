"""
One-off FusionSolar PV log backfill for the logging gaps currently present.

No CLI arguments. The ranges below are intentionally hard-coded. Re-running is
safe: existing 5-minute buckets are kept and only missing buckets are inserted.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PV_LOG_DIR = PROJECT_ROOT / "data" / "logs" / "electricity"
PV_LOG_BASENAME = "pv_inverter.json"
PV_LOGGER_PATH = PROJECT_ROOT / "services" / "pv_logger.py"

# Identifiable PV logger gaps in the repository as of 2026-09-07.
# Boundary days are included deliberately; merge logic only adds missing
# 5-minute buckets, so already-logged samples are left untouched.
BACKFILL_RANGES = [
    ("2026-05-12", "2026-05-20"),
    ("2026-05-30", "2026-05-30"),
    ("2026-06-12", "2026-06-13"),
    ("2026-06-17", "2026-06-17"),
    ("2026-06-23", "2026-06-30"),
    ("2026-07-03", "2026-07-04"),
    ("2026-07-11", "2026-09-07"),
]

# Refresh the browser session periodically during the long July-September gap.
RELOGIN_EVERY_DAYS = 14
TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S"


def load_pv_helpers():
    """Load pv_logger definitions without executing its service-level wrapper."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    src = PV_LOGGER_PATH.read_text(encoding="utf-8")
    marker = "\nsuccess = False\n"
    if marker not in src:
        raise RuntimeError(f"Could not find service wrapper marker in {PV_LOGGER_PATH}")

    helper_src = src.split(marker, 1)[0]
    ns = {
        "__file__": str(PV_LOGGER_PATH),
        "__name__": "pv_logger_backfill_helpers",
    }
    exec(compile(helper_src, str(PV_LOGGER_PATH), "exec"), ns)
    return ns


def login(pv):
    username, password = pv["load_credentials"]()
    driver = pv["make_driver"]()
    wait = pv["WebDriverWait"](driver, 30)
    By = pv["By"]
    EC = pv["EC"]
    ElementNotInteractableException = pv["ElementNotInteractableException"]

    try:
        driver.get(pv["LOGIN_URL"])

        wait.until(EC.visibility_of_element_located((By.ID, "username")))
        wait.until(EC.visibility_of_element_located((By.ID, "value")))
        wait.until(EC.element_to_be_clickable((By.ID, "btn_outerverify")))

        username_el = driver.find_element(By.ID, "username")
        password_el = driver.find_element(By.ID, "value")
        login_btn = driver.find_element(By.ID, "btn_outerverify")

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", username_el
        )
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", password_el
        )
        time.sleep(0.5)

        try:
            username_el.click()
            username_el.clear()
            username_el.send_keys(username)
            password_el.click()
            password_el.clear()
            password_el.send_keys(password)
        except ElementNotInteractableException:
            pv["set_input_value"](driver, username_el, username)
            pv["set_input_value"](driver, password_el, password)

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", login_btn
        )
        time.sleep(0.3)
        try:
            login_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", login_btn)

        time.sleep(5)
        if driver.find_elements(By.ID, "username") and driver.find_elements(
            By.ID, "btn_outerverify"
        ):
            raise RuntimeError("Still on FusionSolar login page after submit")

        try:
            driver.get_log("performance")
        except Exception:
            pass

        driver.get(pv["TREND_URL"])
        time.sleep(6)

        roarand = pv["extract_roarand_from_performance_logs"](driver)
        if not roarand:
            driver.refresh()
            time.sleep(6)
            roarand = pv["extract_roarand_from_performance_logs"](driver)

        if not roarand:
            raise RuntimeError("Did not capture roarand from browser traffic")

        return driver, roarand
    except Exception:
        driver.quit()
        raise


def fetch_signal_map(driver, roarand, pv):
    result = pv["fetch_json"](
        driver=driver,
        url=(
            "/rest/dp/pvms/plant/v1/energy-analyzer/device-tree"
            f"?parentDn={pv['DEVICE_DN']}&treeDepth=signal&_={int(time.time() * 1000)}"
        ),
        roarand=roarand,
    )
    if result["status"] != 200 or not result["json"]:
        raise RuntimeError(f"Could not fetch FusionSolar signal tree: {result}")

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

    walk(result["json"])
    if not signal_map:
        raise RuntimeError("FusionSolar signal tree contained no signals")
    return signal_map


def fetch_day_rows(driver, roarand, pv, signal_map, day):
    signal_ids = sorted(signal_map)
    series_by_signal = {
        sid: {"label": signal_map[sid]["label"], "points": []}
        for sid in signal_ids
    }
    history_url = "/rest/dp/pvms/plant/v1/energy-analyzer/device-history-data"
    timezone_name = None

    for signal_batch in pv["batched"](signal_ids, pv["SIGNAL_BATCH_SIZE"]):
        body = {
            "startTime": day.isoformat(),
            "stationDn": pv["STATION_DN"],
            "endTime": day.isoformat(),
            "signalFilters": pv["build_signal_filters"](signal_batch),
        }
        result = pv["post_json"](
            driver=driver,
            url=history_url,
            body=body,
            roarand=roarand,
        )
        if result["status"] != 200 or not result["json"]:
            raise RuntimeError(
                f"FusionSolar history request failed for {day.isoformat()}: {result}"
            )

        history_json = result["json"]
        timezone_name = history_json.get("timeZone", timezone_name or "UTC")
        tz = ZoneInfo(timezone_name)

        for device_block in history_json.get("data", []):
            for signal_block in device_block.get("signalData", []):
                sid = signal_block.get("signalId")
                if sid not in series_by_signal:
                    continue
                for point in signal_block.get("pmDataList", []):
                    epoch_s = point["startTime"]
                    dt_local = datetime.fromtimestamp(
                        epoch_s, tz=timezone.utc
                    ).astimezone(tz)
                    if dt_local.date() != day:
                        continue
                    series_by_signal[sid]["points"].append(
                        {
                            "epoch": epoch_s,
                            "value": pv["clean_counter_value"](
                                point.get("counterValue")
                            ),
                        }
                    )

    if timezone_name is None:
        return []

    tz = ZoneInfo(timezone_name)
    rows_by_epoch = {}
    for sid, series in series_by_signal.items():
        label = series["label"]
        for point in series["points"]:
            rows_by_epoch.setdefault(point["epoch"], {})[label] = point["value"]

    rows = []
    for epoch in sorted(rows_by_epoch):
        values = rows_by_epoch[epoch]
        if not any(v is not None for v in values.values()):
            continue

        dt_local = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(tz)
        out = {"timestamp": dt_local.strftime(TIMESTAMP_FORMAT)}
        for sid in signal_ids:
            label = signal_map[sid]["label"]
            out[pv["label_to_key"](label)] = values.get(label)
        rows.append(out)

    return rows


def iter_backfill_days():
    seen = set()
    for start_s, end_s in BACKFILL_RANGES:
        start = date.fromisoformat(start_s)
        end = date.fromisoformat(end_s)
        if end < start:
            raise RuntimeError(f"Invalid backfill range: {start_s} .. {end_s}")
        day = start
        while day <= end:
            if day not in seen:
                seen.add(day)
                yield day
            day += timedelta(days=1)


def target_path(day):
    if day == datetime.now().date():
        return PV_LOG_DIR / PV_LOG_BASENAME
    return PV_LOG_DIR / f"{PV_LOG_BASENAME}.{day.isoformat()}"


def parse_timestamp(value):
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def five_minute_bucket(value):
    dt = parse_timestamp(value)
    return dt.replace(
        minute=dt.minute - (dt.minute % 5),
        second=0,
        microsecond=0,
    )


def read_jsonl(path):
    if not path.exists():
        return []

    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON in {path}:{line_no}: {e}") from e
            if "timestamp" not in row:
                raise RuntimeError(f"Missing timestamp in {path}:{line_no}")
            rows.append(row)
    return rows


def write_jsonl_atomic(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pv_backfill.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def merge_day(day, fetched_rows):
    path = target_path(day)
    existing_rows = read_jsonl(path)
    existing_buckets = {
        five_minute_bucket(row["timestamp"]) for row in existing_rows
    }

    additions = []
    added_buckets = set()
    for row in fetched_rows:
        bucket = five_minute_bucket(row["timestamp"])
        if bucket in existing_buckets or bucket in added_buckets:
            continue
        additions.append(row)
        added_buckets.add(bucket)

    if not additions:
        return 0, path

    merged = existing_rows + additions
    merged.sort(key=lambda row: parse_timestamp(row["timestamp"]))
    write_jsonl_atomic(path, merged)
    return len(additions), path


def main():
    pv = load_pv_helpers()
    days = list(iter_backfill_days())
    total_added = 0
    driver = None
    roarand = None
    signal_map = None
    days_on_session = RELOGIN_EVERY_DAYS

    print(
        f"Backfilling {len(days)} calendar days across "
        f"{len(BACKFILL_RANGES)} hard-coded ranges."
    )

    try:
        for i, day in enumerate(days, 1):
            if driver is None or days_on_session >= RELOGIN_EVERY_DAYS:
                if driver is not None:
                    driver.quit()
                print("Refreshing FusionSolar browser session...")
                driver, roarand = login(pv)
                signal_map = fetch_signal_map(driver, roarand, pv)
                days_on_session = 0

            print(
                f"[{i}/{len(days)}] {day.isoformat()}: fetching...",
                end=" ",
                flush=True,
            )
            rows = fetch_day_rows(driver, roarand, pv, signal_map, day)
            added, path = merge_day(day, rows)
            total_added += added
            days_on_session += 1
            print(f"{len(rows)} source rows, {added} inserted -> {path.name}")

    finally:
        if driver is not None:
            driver.quit()

    print(f"Done. Inserted {total_added} missing PV samples.")


if __name__ == "__main__":
    main()
