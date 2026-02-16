from utils.project import *

if True:
    settings["log"] = True
    settings["verbosity"] = False

condensed_schedule = load_json_to_dict('config/scheduling/condensed_schedule.json')

report("Acquiring set temps.",verbose=True)
current_timepoint_info = generate_timepoint_info()
unix_day = current_timepoint_info['unix_day']
hour_of_day = current_timepoint_info['hour_of_day']
interp_hours = 3
set_temps = {}
set_context = {}

for room, schedule_for_days in condensed_schedule.items():
    set_now = schedule_for_days[str(unix_day)][str(hour_of_day)]
    set_context[room] = {}
    for hour_offset in range(-interp_hours,interp_hours+1):
        if 0 <= hour_of_day + hour_offset <= 23:
            offset_temp = schedule_for_days[str(unix_day)][str(hour_of_day + hour_offset)]
            set_context[room][str(hour_offset)] = offset_temp
    if room == "6":
        print(json.dumps(set_context[room], indent=4))
    """
    set_next = set_now
    set_next_hour = hour_of_day
    set_next_day = unix_day
    hours_ahead = 0
    days_ahead = 0
    while set_now == set_next and str(unix_day + days_ahead) in schedule_for_days and hours_ahead < interp_hours:
        hours_ahead += 1
        if 23 < hours_ahead:
            days_ahead += 1
        
        set_next_day = unix_day + days_ahead
        set_next_hour = (hour_of_day + hours_ahead)%23
        
        set_next = schedule_for_days[str(set_next_day)][str(set_next_hour)]
    
    slope = (set_next-set_now)/hours_ahead

    if set_next <= set_now: # Lower, don't interpolate
        set_next = set_now
        hours_ahead = 0
        set_next_hour = hour_of_day
        slope = 0
    
    set_nexts[room] = {"now:": set_now,"next":set_next,"hour":set_next_hour,"hours_ahead":hours_ahead,"slope":format_to_decimals(slope,2)}
    """
    
    set_temps[room] = set_now
    

#print(json.dumps(set_context, indent=4))