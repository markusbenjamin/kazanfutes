import traceback
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb

import log_parser


# Developer test parameters. Edit these, then run:
# python log_parser_test_modes.py

# "AUTO" selects a test date from available dated log files.
# A literal YYYY-MM-DD string forces that date.
TEST_DATE = "AUTO"

# Used only when TEST_DATE = "AUTO".
# "LATEST_PER_MODE": each mode tests its own latest available source day.
# "LATEST_COMMON": all selected modes test the latest date common to all selected sources.
AUTO_DATE_POLICY = "LATEST_PER_MODE"

# "ALL" or an explicit list of mode names, for example:
# TEST_MODES = ["import_heating_control_state", "import_radiator_thermostats"]
TEST_MODES = "ALL"

# "ALL" or a dict of scope_type -> "ALL" / explicit scope_id list.
# Examples:
# TEST_SCOPES = "ALL"
# TEST_SCOPES = {"room": "ALL", "radiator": ["1.1", "1.2", "2.1", "2.3"]}
# TEST_SCOPES = {"heating": ["main"], "heating_cycle": "ALL"}
TEST_SCOPES = "ALL"

# Keep unknown stream IDs in the report even when TEST_SCOPES is explicit.
INCLUDE_UNKNOWN_STREAM_IDS = True

REPORT_DIR = Path(__file__).resolve().parent / "test_reports"

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
    "EMPTY_SELECTION",
    "UNKNOWN_STREAM_IDS",
    "PARSE_EXCEPTION",
    "CONFIG_ERROR",
]


def out(message):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def selected_specs():
    if TEST_MODES == "ALL":
        return SPECS

    selected = {}
    for mode in TEST_MODES:
        if mode not in SPECS:
            selected[mode] = (None, None)
        else:
            selected[mode] = SPECS[mode]
    return selected


def normalize_scope_filter():
    if TEST_SCOPES == "ALL":
        return None

    normalized = {}
    for scope_type, scope_ids in TEST_SCOPES.items():
        if scope_ids == "ALL":
            normalized[scope_type] = None
        else:
            normalized[scope_type] = {str(scope_id) for scope_id in scope_ids}
    return normalized


def source_current_path(source):
    directory, filename = log_parser.SOURCE_FILES[source]
    return log_parser.LOG_PATH / directory / filename


def available_days(source):
    return [day for day, path in log_parser.dated_log_paths(source)]


def latest_available_day(source):
    days = available_days(source)
    if days:
        return days[-1]

    if source_current_path(source).exists():
        return date.today()

    return None


def common_latest_day(specs):
    common = None

    for source, parser in specs.values():
        if source not in log_parser.SOURCE_FILES:
            continue

        days = set(available_days(source))
        if common is None:
            common = days
        else:
            common &= days

    if not common:
        return None

    return max(common)


def test_day_for_source(source, common_day):
    if TEST_DATE != "AUTO":
        return date.fromisoformat(TEST_DATE)

    if AUTO_DATE_POLICY == "LATEST_COMMON":
        return common_day

    if AUTO_DATE_POLICY == "LATEST_PER_MODE":
        return latest_available_day(source)

    raise ValueError(f"unknown AUTO_DATE_POLICY: {AUTO_DATE_POLICY}")


def path_for(source, day):
    if day is None:
        return None

    directory, filename = log_parser.SOURCE_FILES[source]
    archived = log_parser.LOG_PATH / directory / f"{filename}.{day.isoformat()}"
    if archived.exists():
        return archived

    current = log_parser.LOG_PATH / directory / filename
    if day == date.today() and current.exists():
        return current

    return archived


def report_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_part = TEST_DATE if TEST_DATE != "AUTO" else f"auto_{AUTO_DATE_POLICY.lower()}"
    return REPORT_DIR / f"log_parser_test_{date_part}_{timestamp}.txt"


def catalog():
    con = duckdb.connect(str(log_parser.DB_PATH), read_only=True)
    try:
        rows = con.execute("""
        SELECT stream_id, scope_type, scope_id, variable
        FROM streams
        ORDER BY stream_id;
        """).fetchall()
    finally:
        con.close()

    return {
        sid: {
            "scope_type": str(scope),
            "scope_id": str(scope_id),
            "variable": str(var),
        }
        for sid, scope, scope_id, var in rows
    }


def normalize(row):
    if isinstance(row, dict):
        return row.get("timestamp"), row.get("stream_id"), row.get("value")
    if isinstance(row, (tuple, list)) and len(row) >= 3:
        return row[0], row[1], row[2]
    return None


def scope_is_selected(stream_id, streams, scope_filter):
    if scope_filter is None:
        return True

    metadata = streams.get(stream_id)
    if metadata is None:
        return INCLUDE_UNKNOWN_STREAM_IDS

    scope_type = metadata["scope_type"]
    scope_id = metadata["scope_id"]

    if scope_type not in scope_filter:
        return False

    selected_scope_ids = scope_filter[scope_type]
    return selected_scope_ids is None or scope_id in selected_scope_ids


def summarize(rows, streams, day, scope_filter):
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    unknown = Counter()
    scope_counts = Counter()
    stream_counts = Counter()
    timestamps = []
    malformed = []
    before = 0
    after = 0
    parsed_rows = len(rows)
    selected_rows = 0
    skipped_by_scope_filter = 0

    for row in rows:
        item = normalize(row)
        if item is None:
            malformed.append(row)
            continue

        ts, sid, value = item

        if not scope_is_selected(sid, streams, scope_filter):
            skipped_by_scope_filter += 1
            continue

        selected_rows += 1

        metadata = streams.get(sid)
        if metadata is None:
            unknown[sid] += 1
        else:
            scope_type = metadata["scope_type"]
            scope_id = metadata["scope_id"]
            variable = metadata["variable"]
            scope_counts[f"{scope_type}.{scope_id}"] += 1
            stream_counts[f"{scope_type}.{scope_id}.{variable}"] += 1

        if isinstance(ts, datetime):
            timestamps.append(ts)
            if ts < start:
                before += 1
            elif ts >= end:
                after += 1

    status = "PASS"
    if parsed_rows == 0:
        status = "EMPTY_RESULT"
    elif selected_rows == 0:
        status = "EMPTY_SELECTION"
    elif unknown:
        status = "UNKNOWN_STREAM_IDS"
    elif malformed or before or after:
        status = "PASS_WITH_WARNINGS"

    return {
        "status": status,
        "parsed_rows": parsed_rows,
        "selected_rows": selected_rows,
        "skipped_by_scope_filter": skipped_by_scope_filter,
        "unknown": unknown,
        "scope_counts": scope_counts,
        "stream_counts": stream_counts,
        "malformed": malformed,
        "first": min(timestamps) if timestamps else None,
        "last": max(timestamps) if timestamps else None,
        "before": before,
        "after": after,
    }


def run_one(mode, source, parser, streams, day, scope_filter):
    result = {
        "mode": mode,
        "source": source,
        "date": day,
        "status": None,
        "path": None,
        "summary": None,
        "traceback": None,
    }

    if source not in log_parser.SOURCE_FILES or parser is None:
        result["status"] = "CONFIG_ERROR"
        result["traceback"] = "missing source or parser in SPECS"
        return result

    path = path_for(source, day)
    result["path"] = path

    if path is None or not path.exists():
        result["status"] = "MISSING_SOURCE_FILE"
        return result

    try:
        summary = summarize(parser(path), streams, day, scope_filter)
        result["summary"] = summary
        result["status"] = summary["status"]
    except Exception:
        result["status"] = "PARSE_EXCEPTION"
        result["traceback"] = traceback.format_exc()

    return result


def format_scope_filter(scope_filter):
    if scope_filter is None:
        return "ALL"

    parts = []
    for scope_type, scope_ids in sorted(scope_filter.items()):
        if scope_ids is None:
            parts.append(f"{scope_type}: ALL")
        else:
            parts.append(f"{scope_type}: {sorted(scope_ids)}")
    return "; ".join(parts)


def report(results, streams, scope_filter, common_day):
    counts = Counter(r["status"] for r in results)
    lines = [
        "log_parser TEST_MODES report",
        f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"test_date: {TEST_DATE}",
        f"auto_date_policy: {AUTO_DATE_POLICY}",
        f"common_auto_date: {common_day}",
        f"test_modes: {TEST_MODES}",
        f"test_scopes: {format_scope_filter(scope_filter)}",
        f"include_unknown_stream_ids: {INCLUDE_UNKNOWN_STREAM_IDS}",
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
        lines += [
            "",
            f"[{result['status']}] {result['mode']}",
            f"source: {result['source']}",
            f"date: {result['date']}",
            f"path: {result['path']}",
        ]

        summary = result.get("summary")
        if summary:
            lines += [
                f"parsed_rows: {summary['parsed_rows']}",
                f"selected_rows: {summary['selected_rows']}",
                f"skipped_by_scope_filter: {summary['skipped_by_scope_filter']}",
                f"first_timestamp: {summary['first']}",
                f"last_timestamp: {summary['last']}",
                f"out_of_date_rows_before: {summary['before']}",
                f"out_of_date_rows_after: {summary['after']}",
                f"malformed_rows: {len(summary['malformed'])}",
            ]

            if summary["scope_counts"]:
                lines.append("scope_counts:")
                for key, count in sorted(summary["scope_counts"].items()):
                    lines.append(f"  {key}: {count}")

            if summary["stream_counts"]:
                lines.append("stream_counts:")
                for key, count in sorted(summary["stream_counts"].items()):
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
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    specs = selected_specs()
    scope_filter = normalize_scope_filter()
    common_day = common_latest_day(specs) if TEST_DATE == "AUTO" else None

    out("TEST_MODES starting")
    out(f"test_date={TEST_DATE}; auto_date_policy={AUTO_DATE_POLICY}")
    out(f"test_modes={TEST_MODES}")
    out(f"test_scopes={format_scope_filter(scope_filter)}")

    streams = catalog()
    results = []

    for mode, (source, parser) in sorted(specs.items()):
        day = None if source is None else test_day_for_source(source, common_day)
        result = run_one(mode, source, parser, streams, day, scope_filter)
        results.append(result)
        summary = result.get("summary")
        rows = f" parsed={summary['parsed_rows']} selected={summary['selected_rows']}" if summary else ""
        out(f"{result['status']} {mode} date={result['date']}{rows}")

    path = report_path()
    path.write_text(report(results, streams, scope_filter, common_day), encoding="utf-8")
    out(f"report written: {path}")


if __name__ == "__main__":
    main()
