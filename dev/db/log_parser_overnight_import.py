import csv
import re
import shutil
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from time import perf_counter

import db_manager
import log_parser
import log_parser_test_modes


# Edit these, then run: python log_parser_overnight_import.py

INGEST_TARGETS = "ALL_STREAMS_WITH_IMPORTERS"

# Explicit alternatives:
# INGEST_TARGETS = ["room.1.temperature"]
# INGEST_TARGETS = ["room.temperature", "radiator.valve_state"]
# INGEST_TARGETS = [("room", "1", "temperature"), ("radiator", "2.1", "valve_state")]
# INGEST_TARGETS = [{"scope_type": "room", "scope_id": "1", "variable": "temperature"}]

IMPORTER_ORDER = [
    "import_room_temperature_humidity",
    "import_aqara_and_nous",
    "import_room_occupancy",
    "import_room_presence",
    "import_oktopusz_presence",
    "import_heating_control_state",
    "import_pump_power",
    "import_heatmeters",
    "import_radiator_temperatures",
    "import_radiator_thermostats",
    "import_open_close",
    "import_gas_impulses",
    "import_electric_main_meter",
    "import_electric_submeter_impulses",
    "import_pv_inverter",
    "import_weather_station",
    "import_outdoor_weather_com",
]

# Derived occupancy from occupancy/occupancy.json is intentionally excluded from
# long ingestion. room.*.occupancy_state currently comes only from Aqara occupancy.
EXCLUDED_IMPORTERS = ["import_room_occupancy"]

START_AT_IMPORTER = None

# Safety breadcrumb: read dev/db/stream_ingestion_routes.csv before every broad
# ingestion run, then replace this exact string with the required acknowledgement.
ROUTE_REVIEW_ACK = "I_REVIEWED_STREAM_INGESTION_ROUTES_CSV_FOR_THIS_RUN"
REQUIRED_ROUTE_REVIEW_ACK = "I_REVIEWED_STREAM_INGESTION_ROUTES_CSV_FOR_THIS_RUN"

START_DATE = None
END_DATE = None
INCLUDE_CURRENT_LOG = False

IMPORT_EXISTING_POLICY = "skip_existing"

BATCH_FILE_COUNT = 5
REPORT_EVERY_FILES = 10
REPORT_FILE_DETAILS = False

ENABLE_TERMINAL_DASHBOARD = True
TERMINAL_DASHBOARD_MIN_RENDER_SECONDS = 0.25
TERMINAL_DASHBOARD_RECENT_EVENTS = 7
TERMINAL_DASHBOARD_MAX_TARGET_LINES = 4

CREATE_DB_BACKUP = True

# Optional destructive clean rebuild. Leave False for resume/append runs.
# To use: set True, confirm you have a backup, then replace the breadcrumb below.
CLEAR_OBSERVATIONS_BEFORE_IMPORT = False
CLEAR_OBSERVATIONS_ACK = "I_BACKED_UP_AND_WANT_TO_CLEAR_OBSERVATIONS_BEFORE_IMPORT"
REQUIRED_CLEAR_OBSERVATIONS_ACK = (
    "I_BACKED_UP_AND_WANT_TO_CLEAR_OBSERVATIONS_BEFORE_IMPORT"
)

CONTINUE_ON_MODE_FAILURE = False
REFRESH_AVAILABILITY_OUTPUTS = True
ENSURE_DB_SCHEMA_AND_METADATA = True

REPORT_DIR = Path(__file__).resolve().parent / "test_reports"
BACKUP_DIR = Path(__file__).resolve().parent / "store" / "import_backups"
ROUTE_TABLE_PATH = Path(__file__).resolve().parent / "stream_ingestion_routes.csv"


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value):
        for stream in self.streams:
            stream.write(value)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


class TerminalDashboard:
    CLEAR_SCREEN = "\x1b[2J\x1b[H"
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    CYAN = "\x1b[36m"

    PARSED_RE = re.compile(
        r"parsed (?P<done>\d+)/(?P<total>\d+) files .*"
        r"file rows: (?P<file_rows>\d+); "
        r"(?:staged rows: (?P<staged_rows>\d+); )?"
        r"(?:source-reduced: (?P<source_reduced>\d+); )?"
        r"total parsed: (?P<total_parsed>\d+); "
        r"(?:total source-reduced: (?P<total_source_reduced>\d+); )?"
        r"elapsed: (?P<elapsed>[^;]+); "
        r"last file: (?P<last_file>.+)$"
    )
    PREPARING_RE = re.compile(
        r"preparing batch at (?P<done>\d+)/(?P<total>\d+) files; "
        r"pending rows: (?P<pending>\d+)"
    )
    BATCH_START_RE = re.compile(r"batch write starting; rows staged: (?P<rows>\d+)")
    COMMITTED_RE = re.compile(
        r"committed batch at (?P<done>\d+)/(?P<total>\d+) files .*"
        r"batch inserted: (?P<batch_inserted>-?\d+); "
        r"batch skipped existing: (?P<batch_skipped>-?\d+); "
        r"total inserted: (?P<total_inserted>-?\d+); "
        r"total skipped existing: (?P<total_skipped>-?\d+); "
        r"batch time: (?P<batch_time>.+)$"
    )
    UNKNOWN_RE = re.compile(r"unknown: (?P<count>\d+)")

    def __init__(self, stream, enabled=True):
        self.stream = stream
        self.enabled = bool(enabled and getattr(stream, "isatty", lambda: False)())
        self.started_at = perf_counter()
        self.last_render_at = 0
        self.report_path = None
        self.error_path = None
        self.plan_modes = []
        self.current_mode = None
        self.current_mode_index = 0
        self.results = []
        self.errors = []
        self.recent_events = []
        self.last_log_line = None
        self.finished = False

    def set_paths(self, report_path, error_path):
        self.report_path = report_path
        self.error_path = error_path
        self.render(force=True)

    def set_plan(self, plan, skipped_targets, targets):
        self.plan_modes = [mode for mode, _ in plan]
        self.add_event(
            f"planned {len(plan)} importers for {len(targets)} target groups"
        )
        if skipped_targets:
            self.add_event(f"skipped target groups: {len(skipped_targets)}")
        self.render(force=True)

    def start_mode(
        self,
        mode,
        stream_id_filter,
        source_file_count,
        before_total,
        before_streams,
    ):
        try:
            mode_index = self.plan_modes.index(mode) + 1
        except ValueError:
            mode_index = len(self.results) + 1

        self.current_mode_index = mode_index
        self.current_mode = {
            "mode": mode,
            "stage": "starting",
            "source_file_count": source_file_count,
            "target_stream_count": len(stream_id_filter),
            "target_lines": target_summary_lines(stream_id_filter),
            "before_total": before_total,
            "before_streams": before_streams,
            "files_parsed": 0,
            "files_committed": 0,
            "files_total": source_file_count,
            "file_rows": 0,
            "total_parsed": 0,
            "pending_rows": 0,
            "batch_rows": 0,
            "total_inserted": 0,
            "total_skipped": 0,
            "last_file_time": None,
            "mode_elapsed": None,
            "last_batch_time": None,
            "status": "RUNNING",
        }
        self.add_event(f"starting {mode}")
        self.render(force=True)

    def finish_mode(self, result):
        self.results.append(result)
        if self.current_mode and self.current_mode["mode"] == result["mode"]:
            self.current_mode["status"] = result["status"]
            self.current_mode["stage"] = "finished"
            self.current_mode["total_inserted"] = result.get("delta")

        self.add_event(
            f"{result['status']} {result['mode']} delta={result.get('delta')}"
        )
        self.render(force=True)

    def record_error(self, error):
        self.errors.append(error)
        if self.current_mode and error["kind"] in {
            "FAILED_MODE",
            "INTERRUPTED_MODE",
            "KEYBOARD_INTERRUPT",
        }:
            self.current_mode["status"] = error["kind"]
            self.current_mode["stage"] = "attention needed"
        self.add_event(f"{error['kind']}: {error['message']}", level="error")
        self.render(force=True)

    def finish_run(self, results, errors, elapsed_text):
        self.results = results
        self.errors = errors
        self.finished = True
        self.add_event(f"run finished in {elapsed_text}")
        self.render(force=True)

    def handle_line(self, line, is_error=False):
        if not self.enabled:
            return

        clean_line = line.strip()
        if not clean_line:
            return

        self.last_log_line = clean_line

        if is_error:
            self.add_event(clean_line, level="error")
            self.render()
            return

        self.update_from_line(clean_line)

    def update_from_line(self, line):
        if self.current_mode is None:
            return

        if "parsed " in line:
            match = self.PARSED_RE.search(line)
            if match:
                self.current_mode.update({
                    "stage": "parsing",
                    "files_parsed": int(match.group("done")),
                    "files_total": int(match.group("total")),
                    "file_rows": int(match.group("file_rows")),
                    "total_parsed": int(match.group("total_parsed")),
                    "mode_elapsed": match.group("elapsed"),
                    "last_file_time": match.group("last_file"),
                })
                self.render()
                return

        if "preparing batch at" in line:
            match = self.PREPARING_RE.search(line)
            if match:
                self.current_mode.update({
                    "stage": "preparing batch",
                    "files_parsed": int(match.group("done")),
                    "files_total": int(match.group("total")),
                    "pending_rows": int(match.group("pending")),
                })
                self.render()
                return

        if "batch write starting" in line:
            match = self.BATCH_START_RE.search(line)
            if match:
                self.current_mode.update({
                    "stage": "writing batch",
                    "batch_rows": int(match.group("rows")),
                })
                self.render()
                return

        if "checked stream IDs" in line:
            match = self.UNKNOWN_RE.search(line)
            if match and int(match.group("count")):
                self.add_event(line, level="warning")
            self.current_mode["stage"] = "validating stream IDs"
            self.render()
            return

        if "selected new exact observation rows" in line:
            self.current_mode["stage"] = "selecting new rows"
            self.render()
            return

        if "inserted observation rows" in line:
            self.current_mode["stage"] = "inserting rows"
            self.render()
            return

        if "committed batch at" in line:
            match = self.COMMITTED_RE.search(line)
            if match:
                self.current_mode.update({
                    "stage": "batch committed",
                    "files_committed": int(match.group("done")),
                    "files_parsed": int(match.group("done")),
                    "files_total": int(match.group("total")),
                    "total_inserted": int(match.group("total_inserted")),
                    "total_skipped": int(match.group("total_skipped")),
                    "last_batch_time": match.group("batch_time"),
                })
                self.render()
                return

        if "skipped unmapped thermostat keys" in line:
            self.add_event(line, level="warning")
            self.render()

    def add_event(self, message, level="info"):
        self.recent_events.append({
            "level": level,
            "message": message,
            "time": f"{datetime.now():%H:%M:%S}",
        })
        del self.recent_events[:-TERMINAL_DASHBOARD_RECENT_EVENTS]

    def color(self, text, color):
        if not self.enabled:
            return text
        return f"{color}{text}{self.RESET}"

    def render(self, force=False):
        if not self.enabled:
            return

        now = perf_counter()
        if (
            not force
            and now - self.last_render_at < TERMINAL_DASHBOARD_MIN_RENDER_SECONDS
        ):
            return
        self.last_render_at = now

        width = shutil.get_terminal_size((110, 30)).columns
        elapsed_text = format_seconds(now - self.started_at)
        lines = [
            self.color("Overnight DB Import", self.BOLD + self.CYAN),
            f"time: {datetime.now():%Y-%m-%d %H:%M:%S}   elapsed: {elapsed_text}",
        ]

        if self.report_path:
            lines.append(f"log: {self.report_path}")
        if self.error_path:
            lines.append(f"errors: {self.error_path}")

        lines.append("")
        lines.append(self.render_overall(width))
        lines.extend(self.render_current_mode(width))
        lines.extend(self.render_events())
        if self.finished:
            lines.append("")
            lines.append(self.color("run summary written; check error report before trusting the rebuild", self.GREEN))
        else:
            lines.append("")
            lines.append(self.color("Ctrl+C exits after the active batch is rolled back/closed cleanly", self.DIM))

        self.stream.write(self.CLEAR_SCREEN)
        self.stream.write("\n".join(lines[:shutil.get_terminal_size((110, 30)).lines - 1]))
        self.stream.write("\n")
        self.stream.flush()

    def render_overall(self, width):
        total = len(self.plan_modes)
        done = len([result for result in self.results if result["status"] == "DONE"])
        failed = len([result for result in self.results if result["status"] == "FAILED"])
        interrupted = len([
            result for result in self.results if result["status"] == "INTERRUPTED"
        ])
        active = self.current_mode_index if self.current_mode else done
        bar = progress_bar(active, total, width=28)
        status_bits = [
            f"done {done}",
            f"failed {failed}",
            f"interrupted {interrupted}",
            f"errors {len(self.errors)}",
        ]
        return f"overall {bar} {active}/{total or '?'} modes   " + " | ".join(status_bits)

    def render_current_mode(self, width):
        if not self.current_mode:
            return ["", "current: waiting for plan"]

        current = self.current_mode
        files_done = max(current["files_parsed"], current["files_committed"])
        files_total = current["files_total"]
        bar = progress_bar(files_done, files_total, width=34)
        lines = [
            "",
            self.color(f"current: {current['mode']}", self.BOLD),
            f"stage: {current['stage']}   status: {current['status']}",
            f"files: {bar} {files_done}/{files_total}",
            (
                "rows: "
                f"parsed {current['total_parsed']:,} | "
                f"inserted {current['total_inserted']:,} | "
                f"skipped {current['total_skipped']:,} | "
                f"batch {current['batch_rows']:,}"
            ),
        ]
        timing_parts = []
        if current["mode_elapsed"]:
            timing_parts.append(f"mode elapsed {current['mode_elapsed']}")
        if current["last_file_time"]:
            timing_parts.append(f"last file {current['last_file_time']}")
        if current["last_batch_time"]:
            timing_parts.append(f"last batch {current['last_batch_time']}")
        if timing_parts:
            lines.append("timing: " + " | ".join(timing_parts))

        lines.append(
            f"targets: {current['target_stream_count']} streams"
        )
        for target_line in current["target_lines"]:
            lines.append(f"  {target_line}")

        return lines

    def render_events(self):
        lines = ["", self.color("recent", self.BOLD)]
        if not self.recent_events:
            lines.append("  none yet")
            return lines

        for event in self.recent_events:
            marker = "!"
            color = self.RED if event["level"] == "error" else self.YELLOW
            if event["level"] == "info":
                marker = "-"
                color = self.DIM
            lines.append(
                "  "
                + self.color(marker, color)
                + f" {event['time']} {event['message']}"
            )
        return lines


class DashboardStream:
    def __init__(self, dashboard, fallback_stream, is_error=False):
        self.dashboard = dashboard
        self.fallback_stream = fallback_stream
        self.is_error = is_error
        self.buffer = ""

    def write(self, value):
        if not self.dashboard.enabled:
            self.fallback_stream.write(value)
            self.fallback_stream.flush()
            return

        self.buffer += value
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.dashboard.handle_line(line, is_error=self.is_error)

    def flush(self):
        if not self.dashboard.enabled:
            self.fallback_stream.flush()


TERMINAL_DASHBOARD = None


def out(message):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def error_event(kind, message, details=None):
    return {
        "time": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "kind": kind,
        "message": message,
        "details": details,
    }


def write_error_report(error_path, transcript_path, errors):
    lines = [
        "overnight import error report",
        f"generated_at: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"transcript: {transcript_path}",
        "",
    ]

    if not errors:
        lines.append("no errors recorded")
    else:
        lines.append(f"error_count: {len(errors)}")
        for index, error in enumerate(errors, start=1):
            lines += [
                "",
                f"[{index}] {error['kind']}",
                f"time: {error['time']}",
                f"message: {error['message']}",
            ]
            details = error.get("details")
            if details:
                lines += ["details:", str(details).rstrip()]

    error_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_seconds(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds:.0f}s"


def progress_bar(done, total, width=30):
    if not total:
        return "[" + ("-" * width) + "]"

    ratio = max(0, min(1, done / total))
    filled = int(round(width * ratio))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {ratio:.0%}"


def stream_target_group(stream_id):
    parts = str(stream_id).split(".")
    if len(parts) < 3:
        return str(stream_id)
    return f"{parts[0]}.{parts[-1]}"


def target_summary_lines(stream_id_filter):
    groups = {}
    for stream_id in sorted(stream_id_filter):
        group = stream_target_group(stream_id)
        groups[group] = groups.get(group, 0) + 1

    lines = [
        f"{group}: {count}"
        for group, count in sorted(groups.items())
    ]

    if len(lines) <= TERMINAL_DASHBOARD_MAX_TARGET_LINES:
        return lines

    visible = lines[:TERMINAL_DASHBOARD_MAX_TARGET_LINES]
    hidden_count = len(lines) - len(visible)
    visible.append(f"... {hidden_count} more target families")
    return visible


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def validate_importers(importers):
    log_parser_test_modes.validate_importer_registry()

    unknown = sorted(
        mode
        for mode in importers
        if mode not in log_parser.MODE_HANDLERS or mode == "list_modes"
    )
    excluded_unknown = sorted(
        mode
        for mode in EXCLUDED_IMPORTERS
        if mode not in log_parser.MODE_HANDLERS or mode == "list_modes"
    )

    if unknown:
        raise ValueError(f"unknown import modes in plan: {', '.join(unknown)}")
    if excluded_unknown:
        raise ValueError(f"unknown excluded import modes: {', '.join(excluded_unknown)}")


def validate_route_review_gate():
    if ROUTE_REVIEW_ACK != REQUIRED_ROUTE_REVIEW_ACK:
        raise RuntimeError(
            "route review gate is still locked. Read "
            "dev/db/stream_ingestion_routes.csv, confirm the source-log to stream "
            "target routes are right for this run, then replace ROUTE_REVIEW_ACK "
            f"with {REQUIRED_ROUTE_REVIEW_ACK!r} in log_parser_overnight_import.py."
        )

    with ROUTE_TABLE_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    expected_fields = ["source_log_file_name_pattern", "stream_target"]
    if fieldnames != expected_fields:
        raise RuntimeError(
            "stream_ingestion_routes.csv must have exactly these columns before "
            f"a broad import: {', '.join(expected_fields)}. Current columns: "
            f"{', '.join(fieldnames)}"
        )

    unresolved = []
    for index, row in enumerate(rows, start=2):
        joined = " ".join(row.values()).lower()
        if any(marker in joined for marker in ("todo", "fixme", "issue", "?", "review")):
            unresolved.append(index)

    if unresolved:
        raise RuntimeError(
            "stream_ingestion_routes.csv still looks unresolved on line(s): "
            + ", ".join(str(line) for line in unresolved)
        )


def validate_clear_observations_gate():
    if not CLEAR_OBSERVATIONS_BEFORE_IMPORT:
        return

    if CLEAR_OBSERVATIONS_ACK != REQUIRED_CLEAR_OBSERVATIONS_ACK:
        raise RuntimeError(
            "observation clear gate is locked. This run is configured to delete "
            "all rows from observations before importing. Confirm you have a DB "
            "backup, then replace CLEAR_OBSERVATIONS_ACK with "
            f"{REQUIRED_CLEAR_OBSERVATIONS_ACK!r} in log_parser_overnight_import.py."
        )


def ensure_db_schema_and_metadata():
    if not ENSURE_DB_SCHEMA_AND_METADATA:
        return

    out("ensuring database schema and stream metadata")
    db_manager.init_db()
    db_manager.load_stream_metadata()

    stream_count = len(log_parser_test_modes.load_streams())
    if stream_count == 0:
        raise RuntimeError(
            "stream metadata load produced zero streams; cannot build import plan"
        )

    out(f"stream metadata ready: {stream_count} streams")


def configure_log_parser(mode, stream_id_filter):
    log_parser.MODE = mode
    log_parser.START_DATE = START_DATE
    log_parser.END_DATE = END_DATE
    log_parser.INCLUDE_CURRENT_LOG = INCLUDE_CURRENT_LOG
    log_parser.IMPORT_EXISTING_POLICY = IMPORT_EXISTING_POLICY
    log_parser.STREAM_ID_FILTER = stream_id_filter
    log_parser.BATCH_FILE_COUNT = BATCH_FILE_COUNT
    log_parser.REPORT_PROGRESS = True
    log_parser.REPORT_EVERY_FILES = REPORT_EVERY_FILES
    log_parser.REPORT_FILE_DETAILS = REPORT_FILE_DETAILS
    log_parser.validate_import_config()


def observation_snapshot():
    con = log_parser.connect(read_only=True)
    try:
        total = con.execute("SELECT count(*) FROM observations;").fetchone()[0]
        loaded_streams = con.execute("""
        SELECT count(*)
        FROM stream_availability
        WHERE observation_count > 0;
        """).fetchone()[0]
    finally:
        con.close()

    return total, loaded_streams


def checkpoint_database():
    con = log_parser.connect()
    try:
        con.execute("CHECKPOINT;")
    finally:
        con.close()


def make_backup():
    if not CREATE_DB_BACKUP:
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_database()
    backup_path = (
        BACKUP_DIR
        / f"observations.before_overnight_import_{datetime.now():%Y%m%d_%H%M%S}.duckdb"
    )
    shutil.copy2(log_parser.DB_PATH, backup_path)
    return backup_path


def clear_observations_if_requested():
    if not CLEAR_OBSERVATIONS_BEFORE_IMPORT:
        out("clear observations before import: disabled")
        return

    before_total, before_streams = observation_snapshot()
    out(
        "clear observations before import: enabled; "
        f"before observations={before_total}; loaded_streams={before_streams}"
    )

    con = log_parser.connect()
    try:
        con.execute("DELETE FROM observations;")
        con.execute("CHECKPOINT;")
    finally:
        con.close()

    after_total, after_streams = observation_snapshot()
    out(
        "cleared observations; "
        f"after observations={after_total}; loaded_streams={after_streams}"
    )


def source_file_count_for_mode(mode):
    source_name = {
        "import_aqara_and_nous": "aqara_and_nous",
        "import_electric_main_meter": "electric_main_meter",
        "import_electric_submeter_impulses": "electric_submeters",
        "import_gas_impulses": "gas_impulses",
        "import_heatmeters": "heatmeters",
        "import_heating_control_state": "heating_control",
        "import_oktopusz_presence": "oktopusz_presence",
        "import_room_presence": "presence_all",
        "import_open_close": "open_close",
        "import_outdoor_weather_com": "external_temp",
        "import_pump_power": "pumps",
        "import_pv_inverter": "pv_inverter",
        "import_radiator_temperatures": "radiator_temperatures",
        "import_radiator_thermostats": "thermostats",
        "import_room_occupancy": "occupancy",
        "import_room_temperature_humidity": "temperature_and_humidity",
        "import_weather_station": "weather_station",
    }[mode]

    return len(log_parser.configured_source_paths(source_name))


def build_targets():
    streams = log_parser_test_modes.load_streams()
    by_id, by_group = log_parser_test_modes.metadata_indexes(streams)

    if INGEST_TARGETS == "ALL_STREAMS_WITH_IMPORTERS":
        targets = log_parser_test_modes.automatic_targets(by_group)
    else:
        targets = [
            log_parser_test_modes.explicit_target(target, by_id, by_group)
            for target in INGEST_TARGETS
        ]

    return targets


def build_import_plan():
    targets = build_targets()
    planned_stream_ids = {}
    skipped_targets = []
    excluded = set(EXCLUDED_IMPORTERS)

    for target in targets:
        importers = [
            importer
            for importer in log_parser_test_modes.importers_for(target)
            if importer not in excluded
        ]

        if not target["candidate_stream_ids"]:
            skipped_targets.append((target["label"], "no matching metadata streams"))
            continue

        if not importers:
            skipped_targets.append((target["label"], "no importer"))
            continue

        for importer in importers:
            planned_stream_ids.setdefault(importer, set()).update(
                target["candidate_stream_ids"]
            )

    validate_importers(planned_stream_ids)

    plan = [
        (importer, planned_stream_ids[importer])
        for importer in IMPORTER_ORDER
        if importer in planned_stream_ids
    ]

    unordered = sorted(set(planned_stream_ids) - set(IMPORTER_ORDER))
    plan.extend((importer, planned_stream_ids[importer]) for importer in unordered)

    if START_AT_IMPORTER is not None:
        planned_importers = [importer for importer, _ in plan]
        if START_AT_IMPORTER not in planned_importers:
            raise ValueError(
                f"START_AT_IMPORTER is {START_AT_IMPORTER!r}, "
                "but that importer is not in the current plan"
            )

        start_index = planned_importers.index(START_AT_IMPORTER)
        plan = plan[start_index:]

    return plan, skipped_targets, targets


def refresh_availability_outputs():
    if not REFRESH_AVAILABILITY_OUTPUTS:
        return

    db_manager.write_stream_timeline()
    db_manager.write_stream_availability_csv()


def run_mode(mode, stream_id_filter):
    started_at = perf_counter()
    configure_log_parser(mode, stream_id_filter)
    handler = log_parser.MODE_HANDLERS[mode]
    before_total, before_streams = observation_snapshot()
    source_file_count = source_file_count_for_mode(mode)

    if TERMINAL_DASHBOARD is not None:
        TERMINAL_DASHBOARD.start_mode(
            mode=mode,
            stream_id_filter=stream_id_filter,
            source_file_count=source_file_count,
            before_total=before_total,
            before_streams=before_streams,
        )

    out("")
    out(f"=== starting {mode} ===")
    out(f"source files selected: {source_file_count}")
    out(f"target stream IDs: {len(stream_id_filter)}")
    out(f"before: observations={before_total}; loaded_streams={before_streams}")

    handler()

    after_total, after_streams = observation_snapshot()
    elapsed = perf_counter() - started_at
    out(f"after: observations={after_total}; loaded_streams={after_streams}")
    out(f"delta observations: {after_total - before_total}")
    out(f"finished {mode} in {format_seconds(elapsed)}")

    result = {
        "mode": mode,
        "status": "INTERRUPTED" if log_parser.IMPORT_INTERRUPTED else "DONE",
        "target_stream_count": len(stream_id_filter),
        "source_file_count": source_file_count,
        "before_total": before_total,
        "after_total": after_total,
        "delta": after_total - before_total,
        "elapsed_seconds": elapsed,
    }

    if TERMINAL_DASHBOARD is not None:
        TERMINAL_DASHBOARD.finish_mode(result)

    return result


def run_imports():
    errors = []
    started_at = perf_counter()
    validate_route_review_gate()
    validate_clear_observations_gate()
    ensure_db_schema_and_metadata()
    plan, skipped_targets, targets = build_import_plan()

    if TERMINAL_DASHBOARD is not None:
        TERMINAL_DASHBOARD.set_plan(plan, skipped_targets, targets)

    out("overnight log import starting")
    out(f"database: {log_parser.DB_PATH}")
    out(f"log root: {log_parser.LOG_PATH}")
    out(f"start date: {START_DATE or 'first'}")
    out(f"end date: {END_DATE or 'last'}")
    out(f"include current log: {INCLUDE_CURRENT_LOG}")
    out(f"existing observation policy: {IMPORT_EXISTING_POLICY}")
    out(f"create database backup: {CREATE_DB_BACKUP}")
    out(f"clear observations before import: {CLEAR_OBSERVATIONS_BEFORE_IMPORT}")
    out(f"ensure schema and metadata: {ENSURE_DB_SCHEMA_AND_METADATA}")
    out(f"batch file count: {BATCH_FILE_COUNT}")
    out(f"ingest targets: {INGEST_TARGETS}")
    out(f"start at importer: {START_AT_IMPORTER or 'first planned importer'}")
    out(f"target groups: {len(targets)}")
    out(f"planned importers: {', '.join(mode for mode, _ in plan)}")

    if skipped_targets:
        out("skipped targets:")
        for label, reason in skipped_targets:
            out(f"- {label}: {reason}")
            errors.append(
                error_event(
                    "SKIPPED_TARGET",
                    f"{label}: {reason}",
                )
            )
            if TERMINAL_DASHBOARD is not None:
                TERMINAL_DASHBOARD.record_error(errors[-1])

    backup_path = make_backup()
    if backup_path is None:
        out("database backup: disabled")
    else:
        out(f"database backup: {backup_path}")

    clear_observations_if_requested()

    results = []

    for mode, stream_id_filter in plan:
        try:
            result = run_mode(mode, stream_id_filter)
            results.append(result)

            if result["status"] == "INTERRUPTED":
                out("stopping remaining modes because import was interrupted")
                errors.append(
                    error_event(
                        "INTERRUPTED_MODE",
                        f"{mode} was interrupted before the full plan completed",
                    )
                )
                if TERMINAL_DASHBOARD is not None:
                    TERMINAL_DASHBOARD.record_error(errors[-1])
                break

        except KeyboardInterrupt:
            out("overnight runner interrupted by Ctrl+C")
            errors.append(
                error_event(
                    "KEYBOARD_INTERRUPT",
                    "overnight runner interrupted by Ctrl+C",
                )
            )
            if TERMINAL_DASHBOARD is not None:
                TERMINAL_DASHBOARD.record_error(errors[-1])
            break

        except Exception:
            out(f"mode failed: {mode}")
            traceback_text = traceback.format_exc()
            print(traceback_text, end="")
            errors.append(
                error_event(
                    "FAILED_MODE",
                    f"{mode} failed",
                    traceback_text,
                )
            )
            if TERMINAL_DASHBOARD is not None:
                TERMINAL_DASHBOARD.record_error(errors[-1])
            results.append({
                "mode": mode,
                "status": "FAILED",
                "target_stream_count": len(stream_id_filter),
                "source_file_count": None,
                "before_total": None,
                "after_total": None,
                "delta": None,
                "elapsed_seconds": None,
            })

            if not CONTINUE_ON_MODE_FAILURE:
                out("stopping remaining modes because CONTINUE_ON_MODE_FAILURE is False")
                break

    out("")
    out("refreshing availability outputs")
    try:
        refresh_availability_outputs()
    except Exception:
        traceback_text = traceback.format_exc()
        out("availability refresh failed")
        print(traceback_text, end="")
        errors.append(
            error_event(
                "REFRESH_FAILURE",
                "availability refresh failed",
                traceback_text,
            )
        )
        if TERMINAL_DASHBOARD is not None:
            TERMINAL_DASHBOARD.record_error(errors[-1])

    out("")
    out("overnight log import summary")
    for result in results:
        elapsed = result["elapsed_seconds"]
        elapsed_text = "n/a" if elapsed is None else format_seconds(elapsed)
        out(
            f"- {result['status']} {result['mode']}: "
            f"delta={result['delta']}; target_streams={result.get('target_stream_count')}; "
            f"files={result['source_file_count']}; "
            f"elapsed={elapsed_text}"
        )

    elapsed_text = format_seconds(perf_counter() - started_at)
    out(f"total elapsed: {elapsed_text}")
    if TERMINAL_DASHBOARD is not None:
        TERMINAL_DASHBOARD.finish_run(results, errors, elapsed_text)
    return errors


def main():
    global TERMINAL_DASHBOARD

    configure_stdio()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    report_path = REPORT_DIR / f"overnight_import_{run_stamp}.log"
    error_path = REPORT_DIR / f"overnight_import_errors_{run_stamp}.txt"
    errors = []
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    TERMINAL_DASHBOARD = TerminalDashboard(
        original_stdout,
        enabled=ENABLE_TERMINAL_DASHBOARD,
    )
    TERMINAL_DASHBOARD.set_paths(report_path, error_path)

    with report_path.open("w", encoding="utf-8") as report_file:
        if TERMINAL_DASHBOARD.enabled:
            tee_stdout = Tee(
                report_file,
                DashboardStream(TERMINAL_DASHBOARD, original_stdout),
            )
            tee_stderr = Tee(
                report_file,
                DashboardStream(
                    TERMINAL_DASHBOARD,
                    original_stderr,
                    is_error=True,
                ),
            )
        else:
            tee_stdout = Tee(original_stdout, report_file)
            tee_stderr = Tee(original_stderr, report_file)

        with redirect_stdout(tee_stdout), redirect_stderr(tee_stderr):
            out(f"transcript: {report_path}")
            out(f"error report: {error_path}")
            try:
                errors = run_imports()
            except Exception:
                traceback_text = traceback.format_exc()
                out("overnight runner failed before completing summary")
                print(traceback_text, end="")
                errors.append(
                    error_event(
                        "RUNNER_FAILURE",
                        "overnight runner failed before completing summary",
                        traceback_text,
                    )
                )

            write_error_report(error_path, report_path, errors)
            out(f"wrote error report: {error_path}")

    TERMINAL_DASHBOARD = None


if __name__ == "__main__":
    main()
