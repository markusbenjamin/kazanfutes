from utils.project import *

all_rooms_info = get_rooms_info()

rooms_info = {room: info for room, info in all_rooms_info.items() if info["controlled"]}

print(rooms_info)