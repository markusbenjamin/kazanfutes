import traceback
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb
import log_parser

# Edit these, then run: python log_parser_test_modes.py

# Automatic default: one concrete stream example for every scope_type.variable
# combination found in the streams metadata table.
TEST_TARGETS = "AUTO_ONE_PER_SCOPE_VARIABLE"

# Explicit alternatives:
# TEST_TARGETS = ["room.temperature", "radiator.valve_state"]
# TEST_TARGETS = ["radiator.2.1.valve_state", "room.1.temperature"]
# TEST_TARGETS = [("room", "temperature"), ("radiator", "2.1", "valve_state")]
# TEST_TARGETS = [{"scope_type": "room", "variable": "temperature"}]

MAX_DAYS_TO_TRY_PER_IMPORTER = 30
INCLUDE_CURRENT_LOG = False
REPORT_DIR = Path(__file__).resolve().parent / "test_reports"

IMPORTERS = {
    "import_aqara_and_nous": ("aqara_and_nous", log_parser.parse_aqara_and_nous_file),
    "import_electric_main_meter": ("electric_main_meter", lambda p: log_parser.rows_from_mapping_file(p, log_parser.MAIN_METER_FIELD_MAP)),
    "import_electric_submeter_impulses": ("electric_submeters", log_parser.parse_electric_submeter_impulse_file),
    "import_gas_impulses": ("gas_impulses", log_parser.parse_gas_impulse_file),
    "import_heatmeters": ("heatmeters", log_parser.parse_heatmeters_file),
    "import_heating_control_state": ("heating_control", log_parser.parse_heating_control_file),
    "import_oktopusz_presence": ("oktopusz_presence", log_parser.parse_oktopusz_presence_file),
    "import_open_close": ("open_close", log_parser.parse_open_close_file),
    "import_outdoor_weather_com": ("external_temp", log_parser.parse_external_temp_file),
    "import_pump_power": ("pumps", log_parser.parse_pump_power_file),
    "import_pv_inverter": ("pv_inverter", lambda p: log_parser.rows_from_mapping_file(p, log_parser.PV_FIELD_MAP)),
    "import_radiator_temperatures": ("radiator_temperatures", log_parser.parse_radiator_temperatures_file),
    "import_radiator_thermostats": ("thermostats", log_parser.parse_thermostats_file),
    "import_room_occupancy": ("occupancy", log_parser.parse_occupancy_file),
    "import_room_temperature_humidity": ("temperature_and_humidity", log_parser.parse_room_temperature_humidity_file),
    "import_weather_station": ("weather_station", log_parser.parse_weather_station_file),
}

EXACT_IMPORTERS = {
    ("room", "temperature"): ["import_room_temperature_humidity", "import_aqara_and_nous"],
    ("room", "humidity"): ["import_room_temperature_humidity", "import_aqara_and_nous"],
    ("room", "set_temperature"): ["import_heating_control_state"],
    ("room", "occupancy_state"): ["import_room_occupancy"],
    ("room", "presence_detected"): ["import_aqara_and_nous", "import_oktopusz_presence"],
    ("room", "co2"): ["import_aqara_and_nous"],
    ("room", "illuminance"): ["import_aqara_and_nous"],
    ("radiator", "temperature"): ["import_radiator_temperatures", "import_radiator_thermostats"],
    ("radiator", "valve_state"): ["import_heating_control_state", "import_radiator_thermostats"],
    ("heating", "state"): ["import_heating_control_state"],
    ("heating_cycle", "state"): ["import_heating_control_state"],
    ("heating_cycle", "pump_power"): ["import_pump_power"],
    ("heating_cycle", "flow_temperature"): ["import_heatmeters"],
    ("heating_cycle", "return_temperature"): ["import_heatmeters"],
    ("heating_cycle", "volume_flow"): ["import_heatmeters"],
    ("heating_cycle", "power"): ["import_heatmeters"],
    ("heating_cycle", "energy"): ["import_heatmeters"],
    ("heating_cycle", "volume"): ["import_heatmeters"],
    ("door", "state"): ["import_open_close"],
    ("window", "state"): ["import_open_close"],
    ("gas_meter", "impulse"): ["import_gas_impulses"],
    ("electric_submeter", "impulse"): ["import_electric_submeter_impulses"],
    ("outdoor", "temperature"): ["import_outdoor_weather_com"],
}

SCOPE_DEFAULT_IMPORTERS = {
    "electric_main_meter": ["import_electric_main_meter"],
    "pv": ["import_pv_inverter"],
    "weather_station": ["import_weather_station"],
}

STATUSES = [
    "PASS",
    "PASS_WITH_WARNINGS",
    "NO_IMPORTER",
    "NO_AVAILABLE_LOG_DAYS",
    "EMPTY_RESULT",
    "EMPTY_SELECTION",
    "UNKNOWN_STREAM_IDS",
    "PARSE_EXCEPTION",
    "CONFIG_ERROR",
]

PARSE_CACHE = {}


def out(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def load_streams():
    con = duckdb.connect(str(log_parser.DB_PATH), read_only=True)
    try:
        rows = con.execute("""
            SELECT stream_id, scope_type, scope_id, variable
            FROM streams
            ORDER BY scope_type, variable, scope_id, stream_id;
        """).fetchall()
    finally:
        con.close()
    records = []
    for sid, scope_type, scope_id, variable in rows:
        records.append({
            "stream_id": str(sid),
            "scope_type": str(scope_type),
            "scope_id": str(scope_id),
            "variable": str(variable),
        })
    return records


def metadata_indexes(streams):
    by_id = {row["stream_id"]: row for row in streams}
    by_group = defaultdict(list)
    for row in streams:
        by_group[(row["scope_type"], row["variable"])].append(row)
    return by_id, by_group


def make_target(scope_type, variable, rows, label=None):
    stream_ids = sorted(row["stream_id"] for row in rows)
    return {
        "label": label or f"{scope_type}.{variable}",
        "scope_type": scope_type,
        "variable": variable,
        "candidate_stream_ids": set(stream_ids),
        "candidate_stream_count": len(stream_ids),
    }


def automatic_targets(by_group):
    targets = []
    for (scope_type, variable), rows in sorted(by_group.items()):
        targets.append(make_target(scope_type, variable, rows))
    return targets


def explicit_target(item, by_id, by_group):
    if isinstance(item, dict):
        scope_type = str(item["scope_type"])
        variable = str(item["variable"])
        scope_id = item.get("scope_id")
        rows = by_group[(scope_type, variable)]
        if scope_id is not None:
            rows = [row for row in rows if row["scope_id"] == str(scope_id)]
        return make_target(scope_type, variable, rows, str(item))

    if isinstance(item, tuple):
        if len(item) == 2:
            scope_type, variable = map(str, item)
            return make_target(scope_type, variable, by_group[(scope_type, variable)])
        if len(item) == 3:
            scope_type, scope_id, variable = map(str, item)
            rows = [row for row in by_group[(scope_type, variable)] if row["scope_id"] == scope_id]
            return make_target(scope_type, variable, rows, f"{scope_type}.{scope_id}.{variable}")
        raise ValueError(f"unsupported target tuple: {item!r}")

    text = str(item)
    if text in by_id:
        row = by_id[text]
        return make_target(row["scope_type"], row["variable"], [row], text)

    parts = text.split(".")
    if len(parts) == 2:
        scope_type, variable = parts
        return make_target(scope_type, variable, by_group[(scope_type, variable)], text)

    raise ValueError(f"unsupported target specification: {item!r}")


def build_targets(streams):
    by_id, by_group = metadata_indexes(streams)
    if TEST_TARGETS == "AUTO_ONE_PER_SCOPE_VARIABLE":
        return automatic_targets(by_group)
    return [explicit_target(item, by_id, by_group) for item in TEST_TARGETS]


def importers_for(target):
    exact = EXACT_IMPORTERS.get((target["scope_type"], target["variable"]))
    if exact is not None:
        return exact
    return SCOPE_DEFAULT_IMPORTERS.get(target["scope_type"], [])


def current_path(source):
    directory, filename = log_parser.SOURCE_FILES[source]
    return log_parser.LOG_PATH / directory / filename


def day_paths(source):
    paths = list(log_parser.dated_log_paths(source))
    if INCLUDE_CURRENT_LOG and current_path(source).exists():
        paths.append((date.today(), current_path(source)))
    return sorted(paths, reverse=True)


def parse_rows(importer, parser, path):
    key = (importer, str(path))
    if key not in PARSE_CACHE:
        try:
            PARSE_CACHE[key] = ("ok", parser(path))
        except Exception:
            PARSE_CACHE[key] = ("error", traceback.format_exc())
    status, payload = PARSE_CACHE[key]
    if status == "error":
        raise RuntimeError(payload)
    return payload


def normalize(row):
    if isinstance(row, dict):
        return row.get("timestamp"), row.get("stream_id"), row.get("value")
    if isinstance(row, (tuple, list)) and len(row) >= 3:
        return row[0], row[1], row[2]
    return None


def summarize(rows, target, day, by_id):
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    parsed = len(rows)
    selected = 0
    malformed = []
    unknown = Counter()
    selected_streams = Counter()
    timestamps = []
    before = 0
    after = 0

    for row in rows:
        item = normalize(row)
        if item is None:
            malformed.append(row)
            continue
        ts, sid, value = item
        if sid not in by_id:
            unknown[sid] += 1
        if sid not in target["candidate_stream_ids"]:
            continue
        selected += 1
        selected_streams[sid] += 1
        if isinstance(ts, datetime):
            timestamps.append(ts)
            if ts < start:
                before += 1
            elif ts >= end:
                after += 1

    status = "PASS"
    if parsed == 0:
        status = "EMPTY_RESULT"
    elif selected == 0:
        status = "EMPTY_SELECTION"
    elif unknown:
        status = "UNKNOWN_STREAM_IDS"
    elif malformed or before or after:
        status = "PASS_WITH_WARNINGS"

    return {
        "status": status,
        "parsed": parsed,
        "selected": selected,
        "unknown": unknown,
        "selected_streams": selected_streams,
        "example_stream_id": next(iter(selected_streams), None),
        "malformed": malformed,
        "first": min(timestamps) if timestamps else None,
        "last": max(timestamps) if timestamps else None,
        "before": before,
        "after": after,
    }


def candidate_result(target, importer, source, parser, path, day, by_id):
    result = {
        "target": target,
        "importer": importer,
        "source": source,
        "date": day,
        "path": path,
        "status": None,
        "summary": None,
        "traceback": None,
    }
    try:
        summary = summarize(parse_rows(importer, parser, path), target, day, by_id)
        result["summary"] = summary
        result["status"] = summary["status"]
    except Exception:
        result["status"] = "PARSE_EXCEPTION"
        result["traceback"] = traceback.format_exc()
    return result


def score(result):
    summary = result.get("summary") or {}
    if summary.get("selected", 0) > 0:
        return 0
    if result["status"] == "EMPTY_SELECTION":
        return 1
    if result["status"] == "EMPTY_RESULT":
        return 2
    if result["status"] == "PARSE_EXCEPTION":
        return 3
    return 4


def test_target(target, by_id):
    importers = importers_for(target)
    attempts = []

    if not target["candidate_stream_ids"]:
        return {"target": target, "status": "CONFIG_ERROR", "summary": None, "traceback": "target has no matching metadata streams", "attempts": [], "checked": 0, "importer": None, "source": None, "date": None, "path": None}

    if not importers:
        return {"target": target, "status": "NO_IMPORTER", "summary": None, "traceback": None, "attempts": [], "checked": 0, "importer": None, "source": None, "date": None, "path": None}

    for importer in importers:
        source, parser = IMPORTERS[importer]
        paths = day_paths(source)
        if not paths:
            attempts.append({"target": target, "importer": importer, "source": source, "date": None, "path": None, "status": "NO_AVAILABLE_LOG_DAYS", "summary": None, "traceback": None})
            continue
        for day, path in paths[:MAX_DAYS_TO_TRY_PER_IMPORTER]:
            result = candidate_result(target, importer, source, parser, path, day, by_id)
            attempts.append(result)
            if (result.get("summary") or {}).get("selected", 0) > 0:
                best = dict(result)
                best["attempts"] = attempts
                best["checked"] = len(attempts)
                return best

    best = dict(sorted(attempts, key=score)[0]) if attempts else {"target": target, "status": "NO_AVAILABLE_LOG_DAYS", "summary": None, "traceback": None, "importer": None, "source": None, "date": None, "path": None}
    best["attempts"] = attempts
    best["checked"] = len(attempts)
    return best


def write_report(results, streams):
    counts = Counter(result["status"] for result in results)
    lines = [
        "log_parser stream-variable coverage test report",
        f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"test_targets: {TEST_TARGETS}",
        f"max_days_to_try_per_importer: {MAX_DAYS_TO_TRY_PER_IMPORTER}",
        f"include_current_log: {INCLUDE_CURRENT_LOG}",
        f"database: {log_parser.DB_PATH}",
        f"log_root: {log_parser.LOG_PATH}",
        f"metadata_stream_count: {len(streams)}",
        "",
        "summary",
        "-------",
        f"total targets: {len(results)}",
    ]
    for status in STATUSES:
        lines.append(f"{status.lower()}: {counts.get(status, 0)}")

    lines += ["", "targets", "-------"]

    for result in results:
        target = result["target"]
        summary = result.get("summary") or {}
        lines += [
            "",
            f"[{result['status']}] {target['label']}",
            f"scope_type: {target['scope_type']}",
            f"variable: {target['variable']}",
            f"candidate_stream_count: {target['candidate_stream_count']}",
            f"example_stream_id: {summary.get('example_stream_id')}",
            f"importer: {result.get('importer')}",
            f"source: {result.get('source')}",
            f"selected_date: {result.get('date')}",
            f"candidate_attempts_checked: {result.get('checked')}",
            f"path: {result.get('path')}",
        ]
        if summary:
            lines += [
                f"parsed_rows: {summary['parsed']}",
                f"selected_rows: {summary['selected']}",
                f"first_timestamp: {summary['first']}",
                f"last_timestamp: {summary['last']}",
                f"out_of_date_rows_before: {summary['before']}",
                f"out_of_date_rows_after: {summary['after']}",
                f"malformed_rows: {len(summary['malformed'])}",
            ]
            if summary["selected_streams"]:
                lines.append("selected_stream_counts:")
                for stream_id, count in sorted(summary["selected_streams"].items()):
                    lines.append(f"  {stream_id}: {count}")
            if summary["unknown"]:
                lines.append("unknown_stream_ids:")
                for stream_id, count in sorted(summary["unknown"].items()):
                    lines.append(f"  {stream_id}: {count}")
        if result.get("traceback"):
            lines += ["traceback:", result["traceback"].rstrip()]

    path = REPORT_DIR / f"log_parser_stream_variable_test_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    streams = load_streams()
    by_id, by_group = metadata_indexes(streams)
    targets = build_targets(streams)

    out("stream-variable parser test starting")
    out(f"metadata_streams={len(streams)} targets={len(targets)}")

    results = []
    for index, target in enumerate(targets, start=1):
        result = test_target(target, by_id)
        results.append(result)
        summary = result.get("summary") or {}
        out(
            f"{index}/{len(targets)} {result['status']} {target['label']} "
            f"stream={summary.get('example_stream_id')} importer={result.get('importer')} "
            f"date={result.get('date')} selected={summary.get('selected', 'n/a')}"
        )

    out(f"report written: {write_report(results, streams)}")


if __name__ == "__main__":
    main()
