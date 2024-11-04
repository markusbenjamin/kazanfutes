from utils.project import *

system_node = JSONNodeAtURL(node_relative_path='system')
room_temps = get_room_temps_and_humidity()
oktopusz_keramia_temp = (room_temps[11]['temp']+room_temps[12]['temp'])/100
system_node.write({"temp":oktopusz_keramia_temp},'state/oktopusz_keramia')