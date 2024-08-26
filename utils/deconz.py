"""DeCONZ interfacing."""

from utils.base import *

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
    except FileNotFoundError as e:
        raise errors.DeconzSetupError("No deconz_api_url file in secrets_and_env.", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.DeconzSetupError(f"An unexpected error occurred while reading deconz_api_url: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e

    deconz_api_key = ""
    try:
        with open(f'{project_root}/secrets_and_env/deconz_api_key', 'r') as file:
            deconz_api_key = file.read()
    except FileNotFoundError as e:
        raise errors.DeconzSetupError("No deconz_api_key file in secrets_and_env.", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.DeconzSetupError(f"An unexpected error occurred while reading deconz_api_key: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e

    return {'api_url':deconz_api_url,'api_key':deconz_api_key}

def read_and_save_deconz_api_key():
    """
    Reads in the API key from Phoscon app.
    Requires Authenticate app at Phoscon app --> Gateway/conbee/Advanced.
    """

    import requests
    
    deconz_access_params = get_deconz_access_params()
    deconz_api_url = deconz_access_params['api_url']
    if deconz_api_url == "":
        comms.report("First supply Deconz API URL at secrets_and_env.")
        raise errors.DeconzSetupError("Missing Deconz API URL at secrets_and_env", original_exception=None, include_traceback=False)
    
    data = {"devicetype": "conbee_gateway_access"}
    try:
        response = requests.post(deconz_api_url, json=data)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx, 5xx)
        
        # Handle successful response
        response_json = response.json()
        
        # Check if the response indicates that authentication is required
        if "error" in response_json and response_json["error"]["type"] == 101:
            comms.report("First press Authenticate app at Phoscon app --> Gateway/conbee/Advanced.")
        elif "success" in response_json:
            # Save the API key
            api_key = response_json["success"]["username"]
            project_root = project.get_project_root()
            with open(f'{project_root}/secrets_and_env/deconz_api_key', 'w') as file:
                file.write(api_key)
            comms.report("Deconz API key successfully obtained and saved.")
        else:
            comms.report("Unexpected response from Deconz API.")
    
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError
     ) as e:
        raise errors.DeconzSetupError(f"Failed to connect to Deconz API: {e}") from e
    except Exception as e:
        raise errors.DeconzSetupError(f"An unexpected error occurred while connecting to Deconz API: {e}") from e

def read_deconz_state():
    """
    Makes data available from the ZigBee mesh.
    """
    import asyncio
    import aiohttp
    from pydeconz.gateway import DeconzSession

    deconz_access_params = get_deconz_access_params()
    full_url = deconz_access_params['api_url']
    try:
        from urllib.parse import urlparse

        parsed_url = urlparse(full_url)
        ip = parsed_url.hostname
        #ip = full_url[full_url.index('http://')+7:full_url.index(':80/api')] # Previous hardcoded way stored for fallback if needed
    except ValueError as e:
        raise errors.DeconzSetupError("Couldn't extract Deconz URL.", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.DeconzSetupError(f"An unexpected error occurred while extracting Deconz URL: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting())  from e
    port = '80'
    api_key = deconz_access_params['api_key']

    async def read_deconz():    
        async with aiohttp.ClientSession() as session:
            deconz_session = DeconzSession(session, ip, port, api_key)
            await deconz_session.refresh_state()

            #for sensor_id, sensor in deconz_session.sensors.items():
            #    comms.report(f"Sensor ID: {sensor_id}, Name: {sensor.name}")
            #for sensor_id, sensor in deconz_session.sensors.items():
            #    if sensor.type == "ZHATemperature":
            #        comms.report(f"Sensor ID: {sensor.name}, Temperature: {sensor.temperature}")
            #    elif sensor.type == "ZHAHumidity":
            #        comms.report(f"Sensor ID: {sensor.name}, Humidity: {sensor.humidity}")
            return deconz_session
    
    try:
        return asyncio.run(read_deconz())
    except (
        aiohttp.ClientError,
        OSError
     ) as e:
        raise errors.DeconzReadError(f"Failed to connect to Deconz API due to client or network error: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.DeconzReadError(f"Failed to connect to Deconz API due to unexpected error:{e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e

def read_sensors():
    """
    Extracts sensor states from overall ZigBee mesh state.
    """
    return read_deconz_state().sensors.items()