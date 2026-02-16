from utils.project import *

heating_config = load_json_to_dict('config/heating_control_config.json')

new_call = select_subtable_from_table(download_google_sheet_to_2D_array(heating_config['heating_control_config_id']),[1,-0],[0,-1])

print(new_call)