"""DeCONZ interfacing."""

import utils.project as project

def get_deconz_access_params():
    """
    Reads in and returns the URL and the API key of the Deconz Phoscon app
    that is used to access and read the ZigBee mesh through ConBee II.
    """
    project_root = project.get_project_root()

    deconz_api_url = ""
    try:
        with open(f'{project_root}/secrets_and_env/deconz_api_url', 'r') as file:
            deconz_api_url = file.read()
    except FileNotFoundError:
        print("No deconz_api_url file in secrets_and_env.")
    except Exception as e:
        print(f"An error occurred: {e}")


    deconz_api_key = ""
    try:
        with open(f'{project_root}/secrets_and_env/deconz_api_key', 'r') as file:
            deconz_api_key = file.read()
    except FileNotFoundError:
        print("No deconz_api_key file in secrets_and_env.")
    except Exception as e:
        print(f"An error occurred: {e}")

    return {'api_url':deconz_api_url,'api_key':deconz_api_key}

def read_and_save_deconz_api_key():
    """
    Reads in the API key from Phoscon app.
    Requires Authenticate app at Phoscon app --> Gateway/conbee/Advanced.
    """

    import os
    import requests

    deconz_access_params = get_deconz_access_params()
    deconz_api_url = deconz_access_params['api_url']
    if deconz_api_url == "":
        print("First supply Deconz API URL at secrets_and_env.")
        exit()
    data = {"devicetype": "pydeconz_example"}

    response = requests.post(deconz_api_url, json=data)

    if response.status_code == 200:
        api_key = response.json()[0]["success"]["username"]
        print("Deconz API key:", api_key)
        project_root = project.get_project_root()
        deconz_api_key_file_path = f'{project_root}/secrets_and_env/deconz_api_key'
        try:
            with open(deconz_api_key_file_path, 'w') as file:
                file.write(api_key)
                print("Deconz API key written to file in secrets_and_env.")
        except Exception as e:
            print(f"An error occurred: {e}")
    else:
        print("First press Authenticate app at Phoscon app --> Gateway/conbee/Advanced.")

def read_deconz_state():
    """
    Makes data available from the ZigBee mesh.
    """
    import asyncio
    import aiohttp
    from pydeconz.gateway import DeconzSession
    import aiofiles

    deconz_access_params = get_deconz_access_params()
    full_url = deconz_access_params['api_url']
    ip = full_url[full_url.index('http://')+7:full_url.index(':80/api')]
    port = '80'
    api_key = deconz_access_params['api_key']

    async def read_deconz():    
        async with aiohttp.ClientSession() as session:
            deconz_session = DeconzSession(session, ip, port, api_key)
            await deconz_session.refresh_state()

            #for sensor_id, sensor in deconz_session.sensors.items():
            #    print(f"Sensor ID: {sensor_id}, Name: {sensor.name}")
            #for sensor_id, sensor in deconz_session.sensors.items():
            #    if sensor.type == "ZHATemperature":
            #        print(f"Sensor ID: {sensor.name}, Temperature: {sensor.temperature}")
            #    elif sensor.type == "ZHAHumidity":
            #        print(f"Sensor ID: {sensor.name}, Humidity: {sensor.humidity}")
            return deconz_session
        
    return asyncio.run(read_deconz())

def read_sensors():
    """
    Extracts sensor states from overall ZigBee mesh state.
    """
    return read_deconz_state().sensors.items()