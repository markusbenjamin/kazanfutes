from utils.project import *

export_path_prefix = "dev/"
rooms_info = get_rooms_info()
heating_config = load_json_to_dict('config/heating_control_config.json')
local_scheduling_files_relative_path = f'{export_path_prefix}config/scheduling/local_scheduling_files'

def get_presence_patterns_with_weekly_cycle_weighted_average(room, day, hour):
    def sort_nested_dict(node):
        """
        Recursively return a copy of *node* whose dict keys
        that are numeric strings are ordered by their numeric value.
        """
        if not isinstance(node, dict):
            return node

        # sort current level, then recurse
        return {
            k: sort_nested_dict(v)
            for k, v in sorted(node.items(), key=lambda kv: int(kv[0]))
        }
    presence_pattern = sort_nested_dict(load_json_to_dict(f"{export_path_prefix}/config/scheduling/local_scheduling_files/occupancy.json")[room])
    weekly_cycle = transpose_2D_array(select_subtable_from_table(
        load_csv_to_2D_array(f"{local_scheduling_files_relative_path}/weekly_cycle_room_{room}.csv"),
        row_selection=[1,-0],
        col_selection=[1,-0]
        ))
    set_presence = float(weekly_cycle[int(day)-1][int(hour)])
    in_threshold = float(heating_config[f"room_{room}_in_threshold"])
    weekly_cycle_weight = float(heating_config[f"room_{room}_weekly_cycle_weight"])
    return max(0, min(1, weekly_cycle_weight * set_presence + (1 - weekly_cycle_weight) * math.floor((presence_pattern[day][hour]/in_threshold))))

print(get_presence_patterns_with_weekly_cycle_weighted_average('2','1','12'))