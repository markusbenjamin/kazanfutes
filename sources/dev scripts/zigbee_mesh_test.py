import asyncio
import aiohttp
from pydeconz import DeconzSession
import time
import random
import requests
import json

gateway_ip = '192.168.22.139'
gateway_port = '80'
gateway_api_key = 'DB0B6FB07E'

async def get_bulb_id():    
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, gateway_ip, gateway_port, gateway_api_key)
        await deconz.refresh_state()

        for light_id, light in deconz.lights.items():
            print(f"Light ID: {light_id}, Name: {light.name}")

def toggle_light(light_id, state_to_put):
    url = f"http://{gateway_ip}:{gateway_port}/api/{gateway_api_key}/lights/{light_id}/"
    print(url)
    getresponse = requests.get(url)
    print(f"first get: {getresponse}")
    print(getresponse.json()["state"]["on"])
    current_state = getresponse.json()
    current_state['state']['on'] = False
    print(current_state["state"]["on"])
    putresponse = requests.put(url, json=current_state)
    print(f"put: {putresponse}")
    getresponse = requests.get(url)
    print(f"second get: {getresponse}")
    print(getresponse.json()["state"]["on"])

async def read_sensors():
    async with aiohttp.ClientSession() as session:
        deconz = DeconzSession(session, gateway_ip, gateway_port, gateway_api_key)
        await deconz.refresh_state()

        for sensor_id, sensor in deconz.sensors.items():
            if sensor.type == "ZHATemperature":
                print(f"Sensor ID: {sensor_id}, Temperature: {sensor.temperature}")
            elif sensor.type == "ZHAHumidity":
                print(f"Sensor ID: {sensor_id}, Humidity: {sensor.humidity}")

def main():
    while True:
        #asyncio.run(control_light())
        asyncio.run(read_sensors())
        #         #time.sleep(2)
        #toggle_light(1,True)
        time.sleep(2)

if __name__ == "__main__":
    main()