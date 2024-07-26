import asyncio
import aiohttp
from pydeconz.gateway import DeconzSession
import time
import json
import aiofiles

# Run with asyncio.run(read_sensors())
ip = '192.168.34.106'
port = '80'
api_key = '78F42741A3' #Előbb get_api_key kell fusson, hogy ez meglegyen.

async def get_lights_dump():
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, ip, port, api_key)
        await deconz.refresh_state()

        # Initialize an empty list to hold sensor data
        lights_data_list = []

        # Iterate over all sensors and collect their raw data
        for id, light in deconz.lights.items():
            try:
                lights_data_list.append(light.raw)
            except Exception as e:
                print(f"Error processing sensor {id}: {e}")

        # Write the collected sensor data to a file
        async with aiofiles.open('lights_dump.json', 'w') as json_file:
            await json_file.write(json.dumps(lights_data_list, indent=4))

async def get_sensor_dump():
    """ Get the last update time for a specific sensor. """
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, ip, port, api_key)
        await deconz.refresh_state()

        # Initialize an empty list to hold sensor data
        sensor_data_list = []

        # Iterate over all sensors and collect their raw data
        for sensor_id, sensor in deconz.sensors.items():
            try:
                sensor_data_list.append(sensor.raw)
            except Exception as e:
                print(f"Error processing sensor {sensor_id}: {e}")

        # Write the collected sensor data to a file
        async with aiofiles.open('sensor_dumps.json', 'w') as json_file:
            await json_file.write(json.dumps(sensor_data_list, indent=4))

async def read_sensors():    
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, ip, port, api_key)
        await deconz.refresh_state()

        for sensor_id, sensor in deconz.sensors.items():
            types = ["ZHATemperature","ZHAPresence"] #ID: 70
            if sensor.type in types:
                print(f"Sensor ID: {sensor_id}, Name: {sensor.name}")

import aiohttp
from pydeconz.gateway import DeconzSession

async def toggle_light_by_name(bulb_name):
    ip = '192.168.34.106'  # Your bridge IP
    port = '80'  # Your bridge port
    api_key = '78F42741A3'  # Your API key

    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, ip, port, api_key)
        await deconz.refresh_state()

        target_light_id = None
        for id, light in deconz.lights.items():
            if light.name == bulb_name:
                target_light_id = id
                break

        if target_light_id is not None:
            # Directly use the .state field for the current state
            current_state = deconz.lights[target_light_id].state
            # Correctly toggle the state
            new_state = not current_state
            # Send the request to change the light state
            url = f"http://{ip}:{port}/api/{api_key}/lights/{target_light_id}/state"
            async with session.put(url, json={"on": new_state}) as response:
                response_data = await response.json()
                print(response_data)
        else:
            print(f"Light named '{bulb_name}' not found.")

async def set_color_temperature_by_name(bulb_name, ct_value):
    ip = '192.168.34.106'  # Your bridge IP
    port = '80'  # Your bridge port
    api_key = '78F42741A3'  # Your API key

    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, ip, port, api_key)
        await deconz.refresh_state()

        target_light_id = None
        for id, light in deconz.lights.items():
            if light.name == bulb_name:
                target_light_id = id
                break

        if target_light_id is not None:
            # Send the request to change the light's color temperature
            url = f"http://{ip}:{port}/api/{api_key}/lights/{target_light_id}/state"
            async with session.put(url, json={"ct": ct_value}) as response:
                response_data = await response.json()
                print(response_data)
        else:
            print(f"Light named '{bulb_name}' not found.")

async def set_color_temp_globally(temp):
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, ip, port, api_key)
        await deconz.refresh_state()
        bulb_ids = []
        
        for id, light in deconz.lights.items():
            bulb_ids.append(id)
        
        for id in bulb_ids:
            url = f"http://{ip}:{port}/api/{api_key}/lights/{id}/state"
            async with session.put(url, json={"ct": temp}) as response:
                response_data = await response.json()
                print(response_data)

if __name__ == "__main__":
    #while True:
    #asyncio.run(get_sensor_dump())
    #asyncio.run(read_sensors())
        #time.sleep(10)
    #asyncio.run(get_lights_dump())
    #while True:
    #    asyncio.run(toggle_light_by_name("8_tuzzaro"))
    #    exit()
    asyncio.run(set_color_temp_globally(500))