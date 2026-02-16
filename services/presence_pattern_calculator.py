from utils.project import *

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

    minute_resolution = 5
    occupancy_threshold = 15
    for day in data_days:
        start_of_day = day.replace(hour=0, minute=0, second=0, microsecond=0)
        log_for_day = load_ndjson_to_json_list(f"{log_file_path}.{day.strftime('%Y-%m-%d')}")
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
                rf = rel_freq(occ_for_hour[room])
                if True in rf:
                    occupancy_patterns[room][day_of_week][h].append(rf[True])
                else:
                    occupancy_patterns[room][day_of_week][h].append(0)

    for room, days in occupancy_patterns.items():
        for day, hours in days.items():
            for hour in hours:
                occupancy_patterns[room][day][hour] = mean_without_none(occupancy_patterns[room][day][hour], 0)

    export_dict_as_json(occupancy_patterns,f"{export_path_prefix}/config/scheduling/local_scheduling_files/occupancy.json")
    report(f"Succesfully extracted presence patterns.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException(f"Module error while extracting presence patterns.", original_exception=e, severity = 2)
except Exception:
    ServiceException(f"Module error while extracting presence patterns.", severity = 2)