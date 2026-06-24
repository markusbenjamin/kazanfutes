import os
import traceback
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb

import log_parser


TEST_DATE = os.environ.get("TEST_DATE", "2026-03-01")
REPORT_DIR = Path(__file__).resolve().parent / "test_reports"
REPORT_PATH = REPORT_DIR / f"log_parser_test_{TEST_DATE}.txt"

SPECS = {
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

STATUSES = [
    "PASS",
    "PASS_WITH_WARNINGS",
    "MISSING_SOURCE_FILE",
    "EMPTY_RESULT",
    "UNKNOWN_STREAM_IDS",
    "PARSE_EXCEPTION",
    "CONFIG_ERROR",
]


def out(message):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def path_for(source, day):
    directory, filename = log_parser.SOURCE_FILES[source]
    archived = log_parser.LOG_PATH / directory / f"{filename}.{day.isoformat()}"
    if archived.exists():
        return archived
    current = log_parser.LOG_PATH / directory / filename
    if day == date.today() and current.exists():
        return current
    return archived


def catalog():
    con = duckdb.connect(str(log_parser.DB_PATH), read_only=True)
    try:
        rows = con.execute("SELECT stream_id, scope_type, variable FROM streams").fetchall()
    finally:
        con.close()
    return {sid: (scope, var) for sid, scope, var in rows}


def normalize(row):
    if isinstance(row, dict):
        return row.get("timestamp"), row.get("stream_id"), row.get("value")
    if isinstance(row, (tuple, list)) and len(row) >= 3:
        return row[0], row[1], row[2]
    return None


def summarize(rows, streams, day):
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    unknown = Counter()
    groups = Counter()
    timestamps = []
    malformed = []
    before = 0
    after = 0

    for row in rows:
        item = normalize(row)
        if item is None:
            malformed.append(row)
            continue
        ts, sid, value = item
        if sid not in streams:
            unknown[sid] += 1
        else:
            scope, var = streams[sid]
            groups[f"{scope}.{var}"] += 1
        if isinstance(ts, datetime):
            timestamps.append(ts)
            if ts < start:
                before += 1
            elif ts >= end:
                after += 1

    status = "PASS"
    if not rows:
        status = "EMPTY_RESULT"
    elif unknown:
        status = "UNKNOWN_STREAM_IDS"
    elif malformed or before or after:
        status = "PASS_WITH_WARNINGS"

    return {
        "status": status,
        "rows": len(rows),
        "unknown": unknown,
        "groups": groups,
        "malformed": malformed,
        "first": min(timestamps) if timestamps else None,
        "last": max(timestamps) if timestamps else None,
        "before": before,
        "after": after,
    }


def run_one(mode, source, parser, streams, day):
    result = {"mode": mode, "source": source, "status": None, "path": None, "summary": None, "traceback": None}
    if source not in log_parser.SOURCE_FILES or parser is None:
        result["status"] = "CONFIG_ERROR"
        result["traceback"] = "missing source or parser in SPECS"
        return result
    path = path_for(source, day)
    result["path"] = path
    if not path.exists():
        result["status"] = "MISSING_SOURCE_FILE"
        return result
    try:
        summary = summarize(parser(path), streams, day)
        result["summary"] = summary
        result["status"] = summary["status"]
    except Exception:
        result["status"] = "PARSE_EXCEPTION"
        result["traceback"] = traceback.format_exc()
    return result


def report(results, streams, day):
    counts = Counter(r["status"] for r in results)
    lines = [
        "log_parser TEST_MODES report",
        f"date: {day.isoformat()}",
        f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"database: {log_parser.DB_PATH}",
        f"log_root: {log_parser.LOG_PATH}",
        f"stream_catalog_count: {len(streams)}",
        "",
        "summary",
        "-------",
        f"total modes: {len(results)}",
    ]
    for status in STATUSES:
        lines.append(f"{status.lower()}: {counts.get(status, 0)}")
    lines += ["", "modes", "-----"]
    for result in results:
        lines += ["", f"[{result['status']}] {result['mode']}", f"source: {result['source']}", f"path: {result['path']}"]
        summary = result.get("summary")
        if summary:
            lines += [
                f"candidate_rows: {summary['rows']}",
                f"first_timestamp: {summary['first']}",
                f"last_timestamp: {summary['last']}",
                f"out_of_date_rows_before: {summary['before']}",
                f"out_of_date_rows_after: {summary['after']}",
                f"malformed_rows: {len(summary['malformed'])}",
            ]
            if summary["groups"]:
                lines.append("scope_variable_counts:")
                for key, count in sorted(summary["groups"].items()):
                    lines.append(f"  {key}: {count}")
            if summary["unknown"]:
                lines.append("unknown_stream_ids:")
                for sid, count in sorted(summary["unknown"].items()):
                    lines.append(f"  {sid}: {count}")
            if summary["malformed"]:
                lines.append("malformed_row_examples:")
                for row in summary["malformed"][:10]:
                    lines.append(f"  {row!r}")
        if result.get("traceback"):
            lines += ["traceback:", result["traceback"].rstrip()]
    return "\n".join(lines) + "\n"


def main():
    day = date.fromisoformat(TEST_DATE)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out(f"TEST_MODES date={day.isoformat()}")
    streams = catalog()
    results = []
    for mode, (source, parser) in sorted(SPECS.items()):
        result = run_one(mode, source, parser, streams, day)
        results.append(result)
        summary = result.get("summary")
        rows = f" rows={summary['rows']}" if summary else ""
        out(f"{result['status']} {mode}{rows}")
    REPORT_PATH.write_text(report(results, streams, day), encoding="utf-8")
    out(f"report written: {REPORT_PATH}")


if __name__ == "__main__":
    main()
