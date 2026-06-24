import traceback
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

import duckdb
import log_parser

# Edit these, then run: python log_parser_test_modes.py
TEST_SCOPES = "ALL"
# TEST_SCOPES = {"radiator": "ALL"}
# TEST_SCOPES = {"room": "ALL", "radiator": ["1.1", "1.2", "2.1", "2.3"]}
MAX_DAYS_TO_TRY_PER_IMPORTER = 30
INCLUDE_CURRENT_LOG = False
INCLUDE_UNKNOWN_STREAM_IDS = True
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

SCOPE_IMPORTERS = {
    "room": ["import_aqara_and_nous", "import_heating_control_state", "import_oktopusz_presence", "import_room_occupancy", "import_room_temperature_humidity"],
    "radiator": ["import_heating_control_state", "import_radiator_temperatures", "import_radiator_thermostats"],
    "heating": ["import_heating_control_state"],
    "heating_cycle": ["import_heatmeters", "import_heating_control_state", "import_pump_power"],
    "door": ["import_open_close"],
    "window": ["import_open_close"],
    "gas_meter": ["import_gas_impulses"],
    "electric_submeter": ["import_electric_submeter_impulses"],
    "electric_main_meter": ["import_electric_main_meter"],
    "pv": ["import_pv_inverter"],
    "weather_station": ["import_weather_station"],
    "outdoor": ["import_outdoor_weather_com"],
}

STATUSES = ["PASS", "PASS_WITH_WARNINGS", "NO_AVAILABLE_LOG_DAYS", "EMPTY_RESULT", "EMPTY_SELECTION", "UNKNOWN_STREAM_IDS", "PARSE_EXCEPTION", "CONFIG_ERROR"]


def out(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def scope_filter():
    if TEST_SCOPES == "ALL":
        return None
    result = {}
    for scope_type, scope_ids in TEST_SCOPES.items():
        result[scope_type] = None if scope_ids == "ALL" else {str(x) for x in scope_ids}
    return result


def selected_importers(filter_):
    if filter_ is None:
        return sorted(IMPORTERS)
    names = set()
    for scope_type in filter_:
        names.update(SCOPE_IMPORTERS.get(scope_type, []))
    return sorted(names)


def current_path(source):
    directory, filename = log_parser.SOURCE_FILES[source]
    return log_parser.LOG_PATH / directory / filename


def day_paths(source):
    paths = list(log_parser.dated_log_paths(source))
    if INCLUDE_CURRENT_LOG and current_path(source).exists():
        paths.append((date.today(), current_path(source)))
    return sorted(paths, reverse=True)


def load_streams():
    con = duckdb.connect(str(log_parser.DB_PATH), read_only=True)
    try:
        rows = con.execute("SELECT stream_id, scope_type, scope_id, variable FROM streams").fetchall()
    finally:
        con.close()
    return {sid: {"scope_type": str(st), "scope_id": str(si), "variable": str(v)} for sid, st, si, v in rows}


def normalize(row):
    if isinstance(row, dict):
        return row.get("timestamp"), row.get("stream_id"), row.get("value")
    if isinstance(row, (tuple, list)) and len(row) >= 3:
        return row[0], row[1], row[2]
    return None


def keep(sid, streams, filter_):
    if filter_ is None:
        return True
    meta = streams.get(sid)
    if meta is None:
        return INCLUDE_UNKNOWN_STREAM_IDS
    ids = filter_.get(meta["scope_type"], "__not_selected__")
    return ids is None or meta["scope_id"] in ids


def summarize(rows, streams, day, filter_):
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    unknown = Counter(); scopes = Counter(); streams_out = Counter()
    malformed = []; timestamps = []
    parsed = len(rows); selected = 0; skipped = 0; before = 0; after = 0
    for row in rows:
        item = normalize(row)
        if item is None:
            malformed.append(row); continue
        ts, sid, value = item
        if not keep(sid, streams, filter_):
            skipped += 1; continue
        selected += 1
        meta = streams.get(sid)
        if meta is None:
            unknown[sid] += 1
        else:
            scopes[f"{meta['scope_type']}.{meta['scope_id']}"] += 1
            streams_out[f"{meta['scope_type']}.{meta['scope_id']}.{meta['variable']}"] += 1
        if isinstance(ts, datetime):
            timestamps.append(ts)
            if ts < start: before += 1
            elif ts >= end: after += 1
    status = "PASS"
    if parsed == 0: status = "EMPTY_RESULT"
    elif selected == 0: status = "EMPTY_SELECTION"
    elif unknown: status = "UNKNOWN_STREAM_IDS"
    elif malformed or before or after: status = "PASS_WITH_WARNINGS"
    return {"status": status, "parsed": parsed, "selected": selected, "skipped": skipped, "unknown": unknown, "scopes": scopes, "streams": streams_out, "malformed": malformed, "first": min(timestamps) if timestamps else None, "last": max(timestamps) if timestamps else None, "before": before, "after": after}


def run_candidate(importer, source, parser, path, day, streams, filter_):
    result = {"importer": importer, "source": source, "date": day, "path": path, "status": None, "summary": None, "traceback": None}
    try:
        result["summary"] = summarize(parser(path), streams, day, filter_)
        result["status"] = result["summary"]["status"]
    except Exception:
        result["status"] = "PARSE_EXCEPTION"
        result["traceback"] = traceback.format_exc()
    return result


def score(result):
    summary = result.get("summary") or {}
    if summary.get("selected", 0) > 0: return 0
    if result["status"] == "EMPTY_SELECTION": return 1
    if result["status"] == "EMPTY_RESULT": return 2
    if result["status"] == "PARSE_EXCEPTION": return 3
    return 4


def run_importer(name, streams, filter_):
    if name not in IMPORTERS:
        return {"importer": name, "source": None, "date": None, "path": None, "status": "CONFIG_ERROR", "summary": None, "traceback": "missing importer", "checked": 0, "attempts": []}
    source, parser = IMPORTERS[name]
    attempts = []
    for day, path in day_paths(source)[:MAX_DAYS_TO_TRY_PER_IMPORTER]:
        result = run_candidate(name, source, parser, path, day, streams, filter_)
        attempts.append(result)
        if (result.get("summary") or {}).get("selected", 0) > 0:
            break
    if not attempts:
        return {"importer": name, "source": source, "date": None, "path": None, "status": "NO_AVAILABLE_LOG_DAYS", "summary": None, "traceback": None, "checked": 0, "attempts": []}
    best = dict(sorted(attempts, key=score)[0])
    best["checked"] = len(attempts); best["attempts"] = attempts
    return best


def filter_text(filter_):
    if filter_ is None:
        return "ALL"
    parts = []
    for scope_type, ids in sorted(filter_.items()):
        parts.append(f"{scope_type}: {'ALL' if ids is None else sorted(ids)}")
    return "; ".join(parts)


def write_report(results, streams, filter_, names):
    counts = Counter(r["status"] for r in results)
    lines = ["log_parser scope-driven parser test report", f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}", f"test_scopes: {filter_text(filter_)}", f"selected_importers: {names}", f"max_days_to_try_per_importer: {MAX_DAYS_TO_TRY_PER_IMPORTER}", f"include_current_log: {INCLUDE_CURRENT_LOG}", f"database: {log_parser.DB_PATH}", f"log_root: {log_parser.LOG_PATH}", f"stream_catalog_count: {len(streams)}", "", "summary", "-------", f"total importers: {len(results)}"]
    for status in STATUSES:
        lines.append(f"{status.lower()}: {counts.get(status, 0)}")
    lines += ["", "importers", "---------"]
    for r in results:
        lines += ["", f"[{r['status']}] {r['importer']}", f"source: {r['source']}", f"selected_date: {r['date']}", f"candidate_dates_checked: {r['checked']}", f"path: {r['path']}"]
        s = r.get("summary")
        if s:
            lines += [f"parsed_rows: {s['parsed']}", f"selected_rows: {s['selected']}", f"skipped_by_scope_filter: {s['skipped']}", f"first_timestamp: {s['first']}", f"last_timestamp: {s['last']}", f"out_of_date_rows_before: {s['before']}", f"out_of_date_rows_after: {s['after']}", f"malformed_rows: {len(s['malformed'])}"]
            if s["scopes"]:
                lines.append("scope_counts:"); lines += [f"  {k}: {v}" for k, v in sorted(s["scopes"].items())]
            if s["streams"]:
                lines.append("stream_counts:"); lines += [f"  {k}: {v}" for k, v in sorted(s["streams"].items())]
            if s["unknown"]:
                lines.append("unknown_stream_ids:"); lines += [f"  {k}: {v}" for k, v in sorted(s["unknown"].items())]
            if s["malformed"]:
                lines.append("malformed_row_examples:"); lines += [f"  {x!r}" for x in s["malformed"][:10]]
        empty_attempts = [a for a in r["attempts"] if (a.get("summary") or {}).get("selected", 0) == 0]
        if empty_attempts:
            lines.append("candidate_dates_without_selected_rows:")
            for a in empty_attempts[:10]:
                s2 = a.get("summary") or {}
                lines.append(f"  {a['date']}: {a['status']}; parsed={s2.get('parsed', 'n/a')}; selected={s2.get('selected', 'n/a')}; path={a['path']}")
        if r.get("traceback"):
            lines += ["traceback:", r["traceback"].rstrip()]
    path = REPORT_DIR / f"log_parser_scope_test_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filter_ = scope_filter(); names = selected_importers(filter_); streams = load_streams()
    out("scope-driven parser test starting")
    out(f"test_scopes={filter_text(filter_)}")
    out(f"selected_importers={names}")
    results = []
    for name in names:
        result = run_importer(name, streams, filter_); results.append(result)
        s = result.get("summary") or {}
        out(f"{result['status']} {name} date={result['date']} checked={result['checked']} parsed={s.get('parsed', 'n/a')} selected={s.get('selected', 'n/a')}")
    out(f"report written: {write_report(results, streams, filter_, names)}")


if __name__ == "__main__":
    main()
