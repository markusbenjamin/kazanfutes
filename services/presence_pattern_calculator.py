from utils.project import *
from utils.occupancy import select_training_sources, filter_training_log
from utils.device_watchdog import atomic_write_json

settings["dev"] = False #DEV
export_path_prefix = ""

if settings["dev"]:
    settings["log"] = False
    settings["verbosity"] = True
    export_path_prefix = "dev/"
try:
    success = False
    log_file_path = r"data/logs/presence/presence_all.json"

    #start_date = datetime(2025, 10, 1)
    start_date = datetime.now() - timedelta(days=28)
    end_date = datetime.now() - timedelta(days=1)
    data_days = []
    current_date = start_date
    while current_date <= end_date:
        data_days.append(current_date)
        current_date += timedelta(days=1)

    rooms_info = get_rooms_info()
    occupancy_patterns = {}
    known_samples = {room: 0 for room in rooms_info}
    training_sources = select_training_sources(load_recent_presence_log(), rooms_info)

    minute_resolution = 5
    occupancy_threshold = 15
    for day in data_days:
        start_of_day = day.replace(hour=0, minute=0, second=0, microsecond=0)
        log_for_day = load_ndjson_to_json_list(f"{log_file_path}.{day.strftime('%Y-%m-%d')}")
        log_for_day = filter_training_log(log_for_day, training_sources)
        day_of_week = generate_timepoint_info(day)['day_of_week']

        hourly_ts = [
            [ (start_of_day + timedelta(hours=h, minutes=m)).strftime('%Y-%m-%d-%H-%M-%S')
            for m in range(0, 60, minute_resolution) ]
            for h in range(0, 24)
        ]

        for h in range(0,24):
            occ_for_hour = transpose_dict(get_rooms_occupancy(log = log_for_day, threshold = occupancy_threshold, timestamps = hourly_ts[h]))
            for room in rooms_info:
                if room not in occupancy_patterns:
                    occupancy_patterns[room] = {}
                if day_of_week not in occupancy_patterns[room]:
                    occupancy_patterns[room][day_of_week] = {}
                if h not in occupancy_patterns[room][day_of_week]:
                    occupancy_patterns[room][day_of_week][h] = []
                known_samples[room] += sum(isinstance(value, bool) for value in occ_for_hour[room].values())
                occupancy_patterns[room][day_of_week][h].append(
                    known_presence_fraction(occ_for_hour[room].values())
                )

    for room, days in occupancy_patterns.items():
        for day, hours in days.items():
            for hour in hours:
                occupancy_patterns[room][day][hour] = mean_without_none(occupancy_patterns[room][day][hour], None)

    coverage = {}
    for room, days in occupancy_patterns.items():
        values = [value for hours in days.values() for value in hours.values()]
        coverage[room] = {
            "known_hours": sum(value is not None for value in values),
            "unknown_hours": sum(value is None for value in values),
            "occupied_hours": sum(value is not None and value > 0 for value in values),
            "known_samples": known_samples[room],
            "training_source": training_sources.get(room),
        }
    log({"occupancy_profile_coverage": coverage})
    have_profiles = any(row["known_hours"] for row in coverage.values())
    if any(known_samples.values()) and not have_profiles:
        raise ModuleException("Usable occupancy samples produced no learned profile values", severity=2)

    occupancy_export_path = os.path.join(
        export_path_prefix,
        "config",
        "scheduling",
        "local_scheduling_files",
        "occupancy.json",
    )
    atomic_write_json(os.path.join(get_project_root(), occupancy_export_path), occupancy_patterns)
    report(f"Succesfully extracted presence patterns.",verbose=True)
    success = have_profiles
    if not have_profiles:
        ServiceException("No usable learned occupancy profiles; weekly fallback remains necessary", severity=2)
except ModuleException as e:
    ServiceException(f"Module error while extracting presence patterns.", original_exception=e, severity = 2)
except Exception:
    ServiceException(f"Module error while extracting presence patterns.", severity = 2)

log({"success": success})
if not success:
    raise SystemExit(1)
