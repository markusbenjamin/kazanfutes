from utils.project import *


#print(get_thermostat_state_by_name("SZGK",["valve","battery","heatsetpoint","temperature","externalsensortemp","lastseen"]))
#exit()

for id in ["77", "79", "71", "75", "42", "59", "63", "69", "65", "53", "57"]:
    #calibrate_thermostat_by_id(int(id))
    set_thermostat_state_by_id(int(id),heatsetpoint = 5)
    time.sleep(5)
    print(get_thermostat_state_by_id(int(id),fields=["name","valve","temperature","heatsetpoint"]))
exit()

for _ in range(50):
    if True:
        for name in ["SZGK","Merce","Merce_targyalo","Lahmacun","Golyairoda","PK","GEP_muhely","Golyafeszek_1","Golyafeszek_2","Oktopusz_szita_1","Oktopusz_szita_2"]:
            set_thermostat_state_by_name(name,heatsetpoint = 22,loadbalancing=False,windowopendetectionenabled=False,externalwindowopen=False)
            print(get_thermostat_state_by_name(name,fields=["name","valve","temperature","heatsetpoint"]))
        #exit()
    else:
        for id in [79]:
            print(get_thermostat_state(sensor_id=id,fields=["name","valve","temperature","heatsetpoint","loadbalancing","windowopendetectionenabled","windowopen"], pretty = False))
            set_thermostat_state(sensor_id=id,heatsetpoint = 16,loadbalancing=False,windowopendetectionenabled=False,externalwindowopen=False)
    time.sleep(90)
exit()


if True:
    #d = get_thermostat_state(sensor_id = id, fields=["name","temperature", "heatsetpoint","lastseen"], pretty=False)
    #print(f"{d['name']}: {d['temperature']/100:.1f} °C  /  set -> {d['heatsetpoint']/100:.1f} °C ({d['lastseen']})")
    #set_thermostat_state(sensor_id = id, heatsetpoint=15)
    #d = get_thermostat_state(sensor_id = id, fields=["name","temperature", "heatsetpoint","lastseen"], pretty=False)
    #print(f"{d['name']}: {d['temperature']/100:.1f} °C  /  set -> {d['heatsetpoint']/100:.1f} °C ({d['lastseen']})")
    # push a fake ambient temp of 21.0 °C
    #set_thermostat_state(sensor_id=id, externalsensortemp=35)
    #print(get_thermostat_state(sensor_id = id, pretty=False))
    # a) push a *high* external temp so the TRV thinks the room is hot
    set_thermostat_state(sensor_id=id,
                        heatsetpoint = 32,
                        loadbalancing=False,
                        windowopendetectionenabled=False,
                        externalwindowopen=False,
                        )

    # b) wait ~60 s and read valve %
    state = get_thermostat_state(sensor_id=id,
                                fields=["name","valve","heatsetpoint","externalsensortemp","temperature","windowopen","lastseen","lastupdated","loadbalancing","windowopendetectionenabled"],
                                pretty=False)
    print(state)

else:
    ok = set_thermostat_state(
            sensor_id=id,                 # ? or None for first TRV
            timeout_s=3,                    # wait up to 3 s for echo
            windowopendetectionenabled=False,
            externalwindowopen=False,
            loadbalancing=False,            # make sure nothing overrides you
            heatsetpoint=21.5               # target �C ? helper auto-scales
    )

    print("write accepted:", ok)            # should be True