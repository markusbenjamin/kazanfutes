import tinytuya
import csv

def load_plug_mappings():
    global room_to_plug, plug_to_id, plug_to_ip, plug_to_key

    room_to_plug = {}
    plug_to_id = {}
    plug_to_ip = {}
    plug_to_key = {}

    with open('plug_info.csv', 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            room = int(row['room'])
            plug_num = int(row['num'])

            # Since a room is associated with one plug, we use direct assignment
            room_to_plug[room] = plug_num
            plug_to_id[plug_num] = str(row['id'])
            plug_to_ip[plug_num] = str(row['ip'])
            plug_to_key[plug_num] = str(row['key'])

def switch_plug(id, ip, key, setting):
    print([id, ip, key, setting])

    plug = tinytuya.OutletDevice(
    dev_id=id,
    address=ip,
    local_key=key,
    version=3.3)

    print(plug.status())

load_plug_mappings()
pump = 1
setting = 1
switch_plug(plug_to_id[pump],plug_to_ip[pump],plug_to_key[pump],setting)