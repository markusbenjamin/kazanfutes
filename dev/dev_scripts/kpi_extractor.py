"""
Extracts various KPIs from logs and writes it to Firebase for the dashboard's benefit.
"""

#region Init

from utils.project import *

settings['dev'] = True

if settings['dev']:
    settings['verbosity'] = False
    settings['log'] = False

#endregion

#region Room level
"""
Degree*hours above set in past n days
Degree*hours below set in past n days
Cycle turnon ratio
"""

rooms_info = get_rooms_info()

#for day in days:
day = datetime.now()
data_root_for_day = f"data/formatted/{daystamp(day)}"

day_metrics = {}
data_expiry = 30
for room, info in rooms_info.items():
    binned_data = {}
    data_types = [
                    {
                        'access':f"room_{room}_measurements",
                        'key':'temp'
                    },
                    {
                        'access':f"room_{room}_set_temps",
                        'key':'set_temp'
                    },
                    {
                        'access':'heating_state',
                        'key':'state'
                    }
                ]

    interpolated_data = {}
    for data_type in data_types:
        loaded = load_json_to_dict(f"{data_root_for_day}/{data_type['access']}.json")

        if data_type['key'] == 'state':
            data_for_type = sorted([
                {
                    'min_of_day': (timestamp_to_datetime(d['timestamp']) - day.replace(hour=0, minute=0, second=0)).total_seconds() / 60,
                    data_type['key']: d['cycle_states'][rooms_info[room]['cycle']]
                }
                for d in loaded if 'cycle_states' in d
            ], key=lambda e: e['min_of_day'])
        elif data_type['key'] == 'temp':
            data_for_type = [
            {
                'min_of_day':(timestamp_to_datetime(d['timestamp'])-day.replace(hour=0, minute=0,second =0)).total_seconds()/60,
                data_type['key']:d['temp']
            }
            for d in loaded
            ]
        elif data_type['key'] == 'set_temp':
            data_for_type = [
                {
                    'min_of_day':(timestamp_to_datetime(d['timestamp'])-day.replace(hour=0, minute=0,second =0)).total_seconds()/60,
                    data_type['key']:d['set_temp']
                }
                for d in loaded
                ]

        times = [d['min_of_day'] for d in data_for_type]

        # Set the maximum allowed gap (in minutes) for using data for interpolation.
        max_gap = data_expiry

        interpolation_for_type = {}

        # Loop over every minute of the day (0 to 1439)
        for m in range(1440):
            # Find the insertion position of m in the sorted times.
            pos = bisect.bisect_left(times, m)
            
            # If m is before the first data point or after the last, we cannot interpolate.
            if pos == 0 or pos == len(times):
                interpolation_for_type[m] = None
                continue

            # The data point immediately before m:
            left_point = data_for_type[pos - 1]
            # The data point immediately after (or at) m:
            right_point = data_for_type[pos]

            # Check the gap conditions:
            if (m - left_point['min_of_day'] > max_gap) or (right_point['min_of_day'] - m > max_gap):
                interpolation_for_type[m] = None
            else:
                # Perform linear interpolation:
                m_left = left_point['min_of_day']
                m_right = right_point['min_of_day']
                t_left = left_point[data_type['key']]
                t_right = right_point[data_type['key']]
                
                # Compute the fractional distance between the two data points:
                factor = (m - m_left) / (m_right - m_left)
                interpolated_val = t_left + factor * (t_right - t_left)
                
                interpolation_for_type[m] = interpolated_val
        
        interpolated_data[data_type['key']] = interpolation_for_type

    turn_on_times = 0
    turn_off_times = 0
    daily_degree_hours_above = 0
    daily_degree_hours_below = 0

    bin_width = 1
    bin_step = 1
    valid_minutes = 0
    bin_minutes = bin_width + (0 if bin_width%2 else bin_width)
    last_state = 0
    for minute_of_day in range(0, 24 * 60, bin_width):
        bin_data = {}
        for data_type in data_types:
            incoming_data_for_type = []
            for minute in range(minute_of_day-bin_width//2,minute_of_day+bin_width//2+1,1):
                if minute in interpolated_data[data_type['key']]:
                    incoming_data_for_type.append(interpolated_data[data_type['key']][minute])
        
            bin_data[data_type['key']] = incoming_data_for_type

        if not any(mean_without_none(value) is None for value in bin_data.values()):
            valid_minutes += 1

            mean_state = mean_without_none(bin_data['state'])
            mean_temp = mean_without_none(bin_data['temp'])
            mean_set_temp = mean_without_none(bin_data['set_temp'])
            mean_comfort_diff = mean_temp - mean_set_temp
            
            mean_control_diff = mean_state * mean_comfort_diff
            if mean_control_diff < 0.5:
                daily_degree_hours_below += mean_control_diff*bin_minutes/60
            elif mean_control_diff > 0.5:
                daily_degree_hours_above += mean_control_diff*bin_minutes/60

            if last_state == 0 and 0 < mean_state and mean_comfort_diff <= 0.5: # This room would turn the cycle on
                turn_on_times += 1
            elif last_state == 1 and mean_state < 1:
                if mean_comfort_diff - 0.5 <= 0.2: # This room would only now be letting the cycle turn off
                    turn_off_times += 1

            last_state = mean_state

    day_validity_ratio = valid_minutes / (minute_of_day()/bin_step  if day == datetime.today() else ((24*60)/bin_step))

    unix_day = generate_timepoint_info(day)['unix_day']

    day_metrics[room] = {
        'validity_ratio' : day_validity_ratio,
        'below' : daily_degree_hours_below,
        'above' : daily_degree_hours_above,
        'turn_on_times': turn_on_times,
        'turn_off_times':turn_off_times
    }

print(json.dumps(day_metrics, indent=4))

#endregion

#region Cycle level
"""
Effect / cost: temp - baseline integrated over time / sent heat
"""

#endregion

#region System level
"""
...
"""

#endregion