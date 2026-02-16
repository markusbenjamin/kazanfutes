from utils.project import *

settings["log"] = False
settings["verbosity"] = True

minutes = range(-10,1)
minutes = [-6*60,-5*60,-4*60,-3*60,-2*60,-1*60,0*60]
minutes = range(-60,1)
occ = get_rooms_occupancy(minutes=minutes)
print(json.dumps(occ,indent=2))
exit()

rooms_occupancy_past_n_minutes = {}

for room, states in transpose_dict(occ).items():
    print(list(states.values()))
    if True in list(states.values()):
        rooms_occupancy_past_n_minutes[room] = True
    elif None in list(states.values()):
        rooms_occupancy_past_n_minutes[room] = None
    else:
        rooms_occupancy_past_n_minutes[room] = False

print(json.dumps(rooms_occupancy_past_n_minutes,indent=2))
    