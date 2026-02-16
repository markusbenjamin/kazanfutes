from utils.project import *
import csv

"""
Mi kell?
- csv-k letöltése
- csv-k beolvasása dictbe
"""

heating_config = load_json_to_dict('config/heating_control_config.json')

url =  f"{heating_config['override_rooms_url']}"
with open(os.path.join(get_project_root(),"config","override.csv"), mode='w', newline='',encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerows(download_csv_to_2D_array(url))

exit()


rooms_info = get_rooms_info()
rooms_schedules_raw = []
for room,info in rooms_info.items():
    print(f"Info for room {room}: {info}")
    url =  f"{heating_config['weekly_schedule_url']}&{info['schedule_gid']}"
    with open(os.path.join(get_project_root(),"config","heating_schedules",f"{room}.csv"), mode='w', newline='',encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerows(download_csv_to_2D_array(url))
    #rooms_schedules_raw.append(download_csv_to_2D_array(url))

exit()
url = f"{heating_config['weekly_schedule_url']}&{rooms_info['1']['schedule_gid']}"

url = heating_config['override_rooms_url']
test_table = download_csv_to_2D_array(url)
print(test_table)
#firebase_node = JSONNodeAtURL(node_relative_path='2dtable')
#firebase_node.write({"table":test_table})
#test_table2 = firebase_node.read()
#jsonified_table = jsonify_array(test_table)

#de_jsonified_table = []



#print(dejsonify_array(jsonified_table))
#exit()