from utils.project import *

system_node = JSONNodeAtURL(node_relative_path='system')
room_temps = get_room_temps_and_humidity(False)
oktopusz_keramia_temp = (room_temps['11']['temp']+room_temps['12']['temp'])/2/100
system_node.write({"1":room_temps['11']['temp']/100,"2":room_temps['12']['temp']/100},'state/oktopusz_keramia')