from datetime import datetime, timedelta

# build used_sensors list
used_temperature_sensor_ids = [10,11,12,13,30,31,34,35]

sensor_raw_list = []
for sensor_id in used_temperature_sensor_ids:
    sensor_raw_list.append(deconz.sensors[sensor_id].raw)


sensor_raw_list = [
   {
        "config": {
            "battery": 0,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "5b193883147c1447ebb73a52f0b1cde3",
        "lastannounced": "2023-11-07T17:06:48Z",
        "lastseen": "2023-11-07T18:16Z",
        "manufacturername": "_TZ2000_a476raq2",
        "modelid": "TS0201",
        "name": "Tuya1",
        "state": {
            "humidity": 6340,
            "lastupdated": "2023-11-07T18:16:23.055"
        },
        "type": "ZHAHumidity",
        "uniqueid": "84:71:27:ff:fe:c6:bd:80-01-0405"
    },
    {
        "config": {
            "battery": 0,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "820868be7994293ae130b9e11b058c51",
        "lastannounced": "2023-11-07T19:15:41Z",
        "lastseen": "2023-11-07T19:15Z",
        "manufacturername": "_TZ2000_a476raq2",
        "modelid": "TS0201",
        "name": "Tuya4",
        "state": {
            "humidity": 5650,
            "lastupdated": "2023-11-07T19:15:46.184"
        },
        "type": "ZHAHumidity",
        "uniqueid": "0c:43:14:ff:fe:4e:98:e0-01-0405"
    },
    {
        "config": {
            "battery": 0,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "dfbb92b38abcd8e770a084ab2718113c",
        "lastannounced": "2023-11-07T17:16:37Z",
        "lastseen": "2023-11-07T17:16Z",
        "manufacturername": "_TZ2000_a476raq2",
        "modelid": "TS0201",
        "name": "Tuya2",
        "state": {
            "lastupdated": "2023-11-07T17:16:41.339",
            "temperature": 2290
        },
        "type": "ZHATemperature",
        "uniqueid": "84:fd:27:ff:fe:16:50:54-01-0402"
    },
    {
        "config": {
            "battery": 0,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "8d9c71bdd96c85cfa908f6c093702cff",
        "lastannounced": "2023-11-07T17:17:06Z",
        "lastseen": "2023-11-07T19:06Z",
        "manufacturername": "_TZ2000_a476raq2",
        "modelid": "TS0201",
        "name": "Tuya3",
        "state": {
            "lastupdated": "2023-11-07T19:06:59.821",
            "temperature": 2310
        },
        "type": "ZHATemperature",
        "uniqueid": "cc:86:ec:ff:fe:c3:b1:71-01-0402"
    },
    {
        "config": {
            "battery": 100,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "da0677559de9004bf42867c489cb675f",
        "lastannounced": "2023-11-07T17:48:06Z",
        "lastseen": "2023-11-07T19:15Z",
        "manufacturername": "eWeLink",
        "modelid": "TH01",
        "name": "Sonoff2",
        "state": {
            "lastupdated": "2023-11-07T19:14:05.802",
            "temperature": 2145
        },
        "swversion": "20211103",
        "type": "ZHATemperature",
        "uniqueid": "00:12:4b:00:25:12:fd:9e-01-0402"
    },
    {
        "config": {
            "battery": 100,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "f7dcf1e3467730a5c136a15b26a32c97",
        "lastannounced": "2023-11-07T16:58:12Z",
        "lastseen": "2023-11-07T19:22Z",
        "manufacturername": "eWeLink",
        "modelid": "TH01",
        "name": "Sonoff5",
        "state": {
            "lastupdated": "2023-11-07T19:22:25.112",
            "temperature": 2222
        },
        "swversion": "20211103",
        "type": "ZHATemperature",
        "uniqueid": "00:12:4b:00:25:12:fd:82-01-0402"
    },
    {
        "config": {
            "battery": 100,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "a226cb07e9f824952bccf1e70f073dd4",
        "lastannounced": 0,
        "lastseen": "2023-11-07T19:20Z",
        "manufacturername": "eWeLink",
        "modelid": "TH01",
        "name": "Sonoff6",
        "state": {
            "lastupdated": "2023-11-07T19:20:49.612",
            "temperature": 2086
        },
        "swversion": "20211103",
        "type": "ZHATemperature",
        "uniqueid": "00:12:4b:00:25:13:04:d0-01-0402"
    },
    {
        "config": {
            "battery": 0,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "d4b3765aa70357ce1e5ea6999a78e4c3",
        "lastannounced": "2023-11-07T17:06:48Z",
        "lastseen": "2023-11-07T18:16Z",
        "manufacturername": "_TZ2000_a476raq2",
        "modelid": "TS0201",
        "name": "Tuya1",
        "state": {
            "lastupdated": "2023-11-07T18:16:22.796",
            "temperature": 2170
        },
        "type": "ZHATemperature",
        "uniqueid": "84:71:27:ff:fe:c6:bd:80-01-0402"
    },
    {
        "config": {
            "battery": 0,
            "offset": 0,
            "on": True,
            "reachable": True
        },
        "ep": 1,
        "etag": "7fed3d3656a4be5eda546419a33bad09",
        "lastannounced": "2023-11-07T19:15:41Z",
        "lastseen": "2023-11-07T19:15Z",
        "manufacturername": "_TZ2000_a476raq2",
        "modelid": "TS0201",
        "name": "Tuya4",
        "state": {
            "lastupdated": "2023-11-07T19:15:46.009",
            "temperature": 2300
        },
        "type": "ZHATemperature",
        "uniqueid": "0c:43:14:ff:fe:4e:98:e0-01-0402"
    }
]

last_updated_list = []
reachable_list = []
temperatures_list = []
for raw in sensor_raw_list:
    last_updated_list.append(datetime.strptime(raw['state']['lastupdated'], '%Y-%m-%dT%H:%M:%S.%f')+timedelta(hours=1))
    reachable_list.append(raw['config']['reachable'])
    if raw['type'] == 'ZHATemperature':
        temperatures_list.append(raw['state']['temperature']/100)

last_updated_by_sensor_id = dict(zip(used_temperature_sensor_ids,last_updated_list))
reachable_by_sensor_id = dict(zip(used_temperature_sensor_ids,reachable_list))
temperatures_by_sensor_id = dict(zip(used_temperature_sensor_ids,temperatures_list))

print(last_updated_by_sensor_id[10].strftime('%m.%d. %H:%M'))
print(reachable_by_sensor_id)
print(temperatures_by_sensor_id)