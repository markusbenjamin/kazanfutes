"""
Common toolkit for the entire project.
Import with: from utils.project import *
"""

#region Imports
import json
import logging
import os
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import filelock

#endregion

#region Settings
class Settings:
    """
    A class to manage configuration settings loaded from a JSON file.

    Attributes:
        settings (dict): A dictionary holding the current settings.

    Methods:
        load_settings_from_file(settings_file): Loads settings from a JSON file.
        get(key): Retrieves the value of a setting by key.
        set(key, value): Modifies or adds a setting.
    """
    def __init__(self, settings_file='settings.json'):
        # Initialize the settings dictionary by loading from the JSON file
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        settings_file = os.path.join(project_root, 'config', 'settings.json')
        self.settings = {}
        self.load_settings_from_file(settings_file)

    def load_settings_from_file(self, settings_file):
        """Load settings from a JSON file."""
        try:
            with open(settings_file, 'r') as file:
                self.settings = json.load(file)
        except FileNotFoundError:
            raise ModuleException(f"settings file {settings_file} not found",severity=1)
        except json.JSONDecodeError:
            raise ModuleException(f"invalid JSON format in {settings_file}",severity=1)
        except Exception:
            raise ModuleException(f"unexpected error occurred while loading the settings file",severity=3)

    def get(self, key):
        """Retrieve a setting value, or None if the key does not exist."""
        try:
            return self.settings.get(key)
        except Exception:
            raise ModuleException(f"error accessing the setting '{key}'",severity=2)

    def set(self, key, value):
        """Modify or add a setting."""
        try:
            self.settings[key] = value
        except Exception:
            raise ModuleException(f"error setting the value for '{key}'",severity=2)
    
settings = Settings()
#endregion

#region Function definitions

#region Comms
"""Everything related to external communication and reporting."""

def report(message, *, verbose = False):
    """Generalized output plug for runtime messages and reporting."""
    if verbose: # Verbose is true for messages that should only be printed in verbose mode.
        if settings.get('verbosity'):
            print(message)
    else:
        print(message)

def notify_admin():
    pass

def send_email(to, subject='', body=''):
    """
    Sends an email using Gmail's SMTP server. Login credentials are loaded from 
    project_root/secrets_and_env/gmail_login.
    
    Args:
        to (str): The recipient's email address.
        subject (str): The subject of the email.
        body (str): The body of the email.
        **kwargs: Additional email headers (optional).
    
    Raises:
        Exception: If sending the email fails for any reason.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    # Path to the login file
    login_file_path = os.path.join(get_project_root(), 'secrets_and_env', 'gmail_login')

    # Read the login credentials from the file
    with open(login_file_path, 'r') as f:
        email_address = f.readline().strip()  # First line: email
        password = f.readline().strip()       # Second line: password

    # Set up the email (headers, subject, body)
    msg = MIMEMultipart()
    msg['From'] = email_address
    msg['To'] = to
    msg['Subject'] = subject

    if isinstance(body, dict):
        body = json.dumps(body, indent=4)  # Pretty-print the dictionary

    # Attach the body as a plain text message
    msg.attach(MIMEText(body, 'plain'))

    success = False

    try:
        # Connect to Gmail's SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()  # Upgrade the connection to a secure encrypted SSL/TLS connection
        server.login(email_address, password)  # Log in to the email account
        text = msg.as_string()  # Convert message to a string
        server.sendmail(email_address, to, text)  # Send the email
        server.quit()
        report(f"Email sent successfully to {to}.",verbose=True)
        success = True
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError):
        raise ModuleException("failed to authenticate with Gmail SMTP server or unsupported operation",severity=1)
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError):
        raise ModuleException("SMTP issue: recipient or sender refused, or data error occurred",severity=1)
    except Exception:
        raise ModuleException(f"unexpected error occurred while sending an email",severity=2)
    
    return success

def log(data: dict):
    """
    Used for runtime logging.
    Logs the provided data to a JSON log file in a hardcoded directory, named after the script calling this function.
    
    Args:
        data (dict): The data to be logged.
    """
    import inspect

    # Get the name of the calling script (the file that called log())
    calling_script_name = os.path.basename(inspect.stack()[1].filename).split('.')[0]

    # Relative path to the log file: default is services directory with the script name in this case
    relative_log_file_path = os.path.join('services', f'{calling_script_name}.json')
    
    # Initialize the logger and log the data
    log_data(data,relative_log_file_path)

def log_data(data: dict, relative_log_file_path: str):
    """
    Used for feature logging.
    Logs the provided data to a specified log file.
    
    Args:
        data (dict): The data to be logged.
        log_file_path (str): Relative path to log file in data/logs/.
    """
    # Initialize the logger and log the data
    init_logger(relative_log_file_path)
    logger = logging.getLogger()
    log_entry = {'timestamp': timestamp()}
    log_entry.update(data)  # Add the rest of the data
    logger.info(json.dumps(log_entry))
    for handler in logger.handlers:
        handler.close()
        logger.removeHandler(handler)

def init_logger(relative_log_file_path: str):
    """
    Initializes the logger with a TimedRotatingFileHandler and adds a timestamp to each log entry.
    Should not normally be called on it's own, but by log() or log_data() as determined by the use-case.
    
    Args:
        log_file (str): Path to the log file.
        when (str): A string representing the time interval for log rotation (default: 'midnight').
        interval (int): The interval for rotating the logs (default: 1).
        timestamp_format (str): The format of the timestamp to be included with each log entry (default: '%Y-%m-%d %H:%M:%S').
    
    """
    logger = logging.getLogger()
    full_log_file_path = os.path.join(get_project_root(),'data','logs', relative_log_file_path)
    log_directory = os.path.dirname(full_log_file_path)
    if not os.path.exists(log_directory):
        os.makedirs(log_directory, exist_ok=True)

    handler = TimedRotatingFileHandler(full_log_file_path, when='midnight', interval=1)
    
    # Define formatter with timestamp
    formatter = logging.Formatter(f'%(message)s')
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def rotate_log_file(relative_log_file_path: str, when: str = 'midnight', interval: int = 1):
    """
    Does rotation of a log file if needed.
    """
    rotation = False
    full_log_file_path = os.path.join(get_project_root(),'data','logs', relative_log_file_path)
    handler = TimedRotatingFileHandler(full_log_file_path, when=when, interval=interval)
    if handler.shouldRollover(int(time.time())):
        handler.doRollover()
        rotation = True
    handler.close()
    return rotation

#endregion

#region Data management
"""Wrapper functions for data management operations."""

def sync_dir_with_repo(project_dir_path, commit_message):
    """
    Pushes a project directory to the GitHub repository.
    """

    import subprocess

    try: 
        os.chdir(os.path.join(get_project_root(), project_dir_path))
    except (FileNotFoundError, PermissionError, OSError):
        raise ModuleException(f"failed to change directory to {project_dir_path}",severity=1)
    except Exception:
        raise ModuleException(f"unexpected error while changing directory to {project_dir_path}",severity=1)

    try:
        subprocess.run(['git', 'add', '.'], check=True)
        
        subprocess.run(['git', 'pull', 'origin','main'], check=True)

        # Check if there are changes staged for commit
        result = subprocess.run(['git', 'diff', '--cached', '--exit-code'], check=False)


        # Only commit and push if there are staged changes
        if result.returncode != 0:
            # Handle 'git commit'
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)

            # Push the changes to the remote repository
            subprocess.run(['git', 'push','-u','origin','main'], check=True)
        else:
            report("No changes staged for commit. Skipping commit and push.")
    except subprocess.CalledProcessError:
        raise ModuleException(f"git command failed",severity=2)
    except Exception:
        raise ModuleException(f"unexpected error while pushing {project_dir_path} to repo",severity=2)
#endregion

#region Deconz
"""DeCONZ interfacing."""

def get_deconz_access_params():
    """
    Reads in and returns the URL and the API key of the Deconz Phoscon app
    that is used to access and read the ZigBee mesh through ConBee II.
    """
    project_root = get_project_root()

    deconz_api_url = ""
    try:
        with open(f'{project_root}/secrets_and_env/deconz_api_url', 'r') as file:
            deconz_api_url = file.read()
    except FileNotFoundError:
        raise ModuleException("no deconz_api_url file in secrets_and_env")
    except Exception:
        raise ModuleException("an unexpected error occurred while reading deconz_api_url",severity=2)

    deconz_api_key = ""
    try:
        with open(f'{project_root}/secrets_and_env/deconz_api_key', 'r') as file:
            deconz_api_key = file.read()
    except FileNotFoundError:
        raise ModuleException("no deconz_api_key file in secrets_and_env")
    except Exception:
        raise ModuleException("unexpected error occurred while reading deconz_api_key",severity=2)

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
        report("First supply Deconz API URL at secrets_and_env.")
        raise ModuleException("missing Deconz API URL at secrets_and_env",severity=2)
    
    data = {"devicetype": "conbee_gateway_access"}
    try:
        response = requests.post(deconz_api_url, json=data)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx, 5xx)
        
        # Handle successful response
        response_json = response.json()
        
        # Check if the response indicates that authentication is required
        if "error" in response_json and response_json["error"]["type"] == 101:
            report("First press Authenticate app at Phoscon app --> Gateway/conbee/Advanced.")
        elif "success" in response_json:
            # Save the API key
            api_key = response_json["success"]["username"]
            project_root = get_project_root()
            with open(f'{project_root}/secrets_and_env/deconz_api_key', 'w') as file:
                file.write(api_key)
            report("Deconz API key successfully obtained and saved.")
        else:
            report("Unexpected response from Deconz API.")
    
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError
     ):
        raise ModuleException("failed to connect to Deconz API",severity=3)
    except Exception:
        raise ModuleException("unexpected error occurred while connecting to Deconz API",severity=3)

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
    except Exception:
        raise ModuleException("unexpected error occurred while extracting Deconz URL",severity=3)
    port = '80'
    api_key = deconz_access_params['api_key']

    async def read_deconz():    
        async with aiohttp.ClientSession() as session:
            deconz_session = DeconzSession(session, ip, port, api_key)
            await deconz_session.refresh_state()

            #for sensor_id, sensor in deconz_session.sensors.items():
            #    report(f"Sensor ID: {sensor_id}, Name: {sensor.name}")
            #for sensor_id, sensor in deconz_session.sensors.items():
            #    if sensor.type == "ZHATemperature":
            #        report(f"Sensor ID: {sensor.name}, Temperature: {sensor.temperature}")
            #    elif sensor.type == "ZHAHumidity":
            #        report(f"Sensor ID: {sensor.name}, Humidity: {sensor.humidity}")
            return deconz_session
    
    try:
        return asyncio.run(read_deconz())
    except (
        aiohttp.ClientError,
        OSError
     ):
        raise ModuleException("failed to connect to Deconz API due to client or network error",severity=3)
    except Exception:
        raise ModuleException("failed to connect to Deconz API due to unexpected error",severity=3)

def read_sensors():
    """
    Extracts sensor states from overall ZigBee mesh state.
    """
    return read_deconz_state().sensors.items()
#endregion

#region Error management
class ServiceException(Exception):
    """Exception class that gets registered when called, should only be called by service scripts."""
    def __init__(self, message, original_exception = None, severity = 0):
        """
        Generates and registers error entry.
        """
        error_entry = {}
        
        try: # If called by a raised exception
            exception_details = extract_exception_details()
            error_entry['message'] = message +': '+exception_details['message']+'.'
            if exception_details['type'] == 'ModuleException':
                error_entry['severity'] = max(severity, original_exception.severity)
            else:
                error_entry['severity'] = severity
            error_entry['origin'] = exception_details['origin']
        except Exception: # If called on it's own (unlikely)
            print(str(e))
            error_entry['message'] = message
            error_entry['severity'] = severity
            error_entry['origin'] = generate_call_origin()
        error_registrar(error_entry)
        super().__init__(message)

class ModuleException(Exception):
    """
    Custom module exception with proposed severity level and origin details.

    Should only be called in module functions.
    """
    def __init__(self, message, severity=0):
        caller_details = extract_exception_details()
        self.severity = severity
        message += ": "+caller_details['message']+' ('+caller_details['type']+')'
        super().__init__(message)

def error_registrar(error_entry):
    """
    Expected keys in a valid error entry: message, severity, origin, origin_timestamp.

    Registers a new error in error_registry.json if not already present and the file is not locked.
    If error_registry.json is locked, appends the error to error_buffer.json for later retry.
    Automatically sets default values for metadata (reported, timestamps, etc.).
    
    Parameters:
    an error_entry dict containing the message, severity, origin and origin timestamp info,
    as generated by the ServiceException class.

    Returns true only if an error has been registered into the error registry, false otherwise.
    """

    # Define the hardcoded paths to the error registry and buffer using the absolute project root
    ERROR_REGISTRY_PATH = f"{get_project_root()}/data/errors/error_registry.json"
    ERROR_BUFFER_PATH = f"{get_project_root()}/data/errors/error_buffer.json"
    
    error_entry.update({
        "registration_timestamp": None,
        "reported": False,
        "reported_timestamp": None,
        "checked": False,
        "checked_timestamp": None
    })

    success = False
    
    # Step 1: Ensure error_registry.json exists, create if missing
    if not os.path.exists(ERROR_REGISTRY_PATH):
        with open(ERROR_REGISTRY_PATH, 'w') as f:
            json.dump([], f)
            report("Created new error registry file.", verbose = True)
    
    try: # Step 2: Try to acquire a lock on the error_registry.json file
        report("Checking lock on error registry.", verbose = True)
        with filelock.FileLock(ERROR_REGISTRY_PATH + ".lock", timeout=1):
            report("Locking error registry.", verbose = True)
            # Step 2a: Open and read the current error registry
            with open(ERROR_REGISTRY_PATH, 'r') as f:
                error_registry = json.load(f)
                report("Existing error registry loaded.", verbose = True)

            # Step 2b: Check if the error is already registered based on its identity
            already_registered = False
            report("Checking if error entry is already registered.", verbose = True)
            for existing_error in error_registry:
                if (
                    existing_error["severity"] == error_entry["severity"] and
                    existing_error["origin"] == error_entry["origin"]
                    ):
                    already_registered = True
                    report("Error entry already in registry, exiting registrar.", verbose = True)
                    break

            # If the error is not already registered, append it
            if not already_registered:
                error_entry["registration_timestamp"] = time.strftime(settings.get('timestamp_format'))
                error_registry.append(error_entry)
                
                # Step 2c: Write the updated registry back to file
                with open(ERROR_REGISTRY_PATH, 'w') as f:
                    json.dump(error_registry, f, indent=4)
                    report("New error, entry registered.", verbose = True)
                    success = True
    except filelock.Timeout:
        report("Error registry locked.", verbose = True)
        # Step 3: Ensure error_buffer.json exists, create if missing
        if not os.path.exists(ERROR_BUFFER_PATH):
            with open(ERROR_BUFFER_PATH, 'w') as f:
                json.dump([], f)
                report("Created new error buffer file.", verbose = True)
        
        # Step 3a: If error_registry.json is locked, write to the error_buffer.json
        report("Locking error buffer.", verbose = True)
        try:
            with filelock.FileLock(ERROR_BUFFER_PATH + ".lock", timeout = 0):
                with open(ERROR_BUFFER_PATH, 'r') as f:
                    error_buffer = json.load(f)
                    report("Error buffer loaded.", verbose = True)
                    
                # Step 3b: Append the error to the buffer
                error_buffer.append(error_entry)
                
                # Step 3c: Write the buffer back to file
                with open(ERROR_BUFFER_PATH, 'w') as f:
                    json.dump(error_buffer, f, indent=4)
                    report("Error entry written to buffer.", verbose = True)
        except:
            report("Error buffer locked, exiting.", verbose = True)

    return success

def extract_exception_details():
    """
    Works only if called after an exception has been raised.

    Returns a dict containing: type, message and origin.
    """
    try:
        import sys
        exc_type, exc_message, tb = sys.exc_info()
        
        exception_details = {
            'type': exc_type.__name__,
            'message': str(exc_message),
            'origin': None
        }

        origin_chain = []

        while tb:
            filename = tb.tb_frame.f_code.co_filename.split('\\')[-1]
            scope = tb.tb_frame.f_code.co_name or 'main_scope'
            line = tb.tb_lineno
            origin_chain.append(f'{filename}{'/'+scope if scope != '<module>' else ''}:{line}')
            tb = tb.tb_next

        exception_details['origin'] = ' --> '.join(origin_chain)
        return exception_details
    except:
        report("Couldn't extract exception details, likely because no exception has been raised.")

def generate_call_origin():
    """
    Extracts detailed information from the current stack trace.

    Returns:
        str: A formatted string representing the call stack up to the topmost frame.
             Format: 'filename/function:line --> filename/function:line --> ...'
    """
    import inspect
    from typing import List

    stack = inspect.stack()
    origin_chain: List[str] = []

    for frame_info in stack[1:]:  # Skip the current frame
        filename = os.path.basename(frame_info.filename)
        function = frame_info.function if frame_info.function != '<module>' else ''
        if function == '__init__' or filename == '__init__.py':
            continue
        line = frame_info.lineno
        if function:
            origin_chain.append(f"{filename}/{function}:{line}")
        else:
            origin_chain.append(f"{filename}:{line}")

    origin = ' --> '.join(origin_chain)
    return origin


#endregion

#region IO
"""Wrapper functions for everything IO."""

def get_room_temps_and_humidity():
    """
    Returns dated temperature and humidity readings for all rooms in config.
    """

    try:
        sensors_state = read_sensors()

        sensor_temps_and_hums = {}
        for sensor_id, sensor in sensors_state:
            if sensor.type == "ZHATemperature":
                last_updated = datetime.strptime((sensor.raw)['state']['lastupdated'], "%Y-%m-%dT%H:%M:%S.%f").strftime(settings.get('timestamp_format'))
                if sensor.name not in sensor_temps_and_hums:
                    sensor_temps_and_hums[sensor.name] = {'temp':'none','hum':'none','last_updated':'none'}
                sensor_temps_and_hums[sensor.name]['temp'] = sensor.temperature
                sensor_temps_and_hums[sensor.name]['last_updated'] = last_updated
            elif sensor.type == "ZHAHumidity":
                last_updated = datetime.strptime((sensor.raw)['state']['lastupdated'], "%Y-%m-%dT%H:%M:%S.%f").strftime(settings.get('timestamp_format'))
                if sensor.name not in sensor_temps_and_hums:
                    sensor_temps_and_hums[sensor.name] = {'temp':'none','hum':'none','last_updated':'none'}
                sensor_temps_and_hums[sensor.name]['hum'] = sensor.humidity
                sensor_temps_and_hums[sensor.name]['last_updated'] = last_updated

        rooms_info = get_rooms_info()

        room_temps_and_hums = {}
        for room_id in rooms_info:
            if rooms_info[room_id]['sensor'] in sensor_temps_and_hums:
                room_temps_and_hums[room_id] = {
                    "temp":sensor_temps_and_hums[rooms_info[room_id]['sensor']]['temp'],
                    "hum":sensor_temps_and_hums[rooms_info[room_id]['sensor']]['hum'],
                    "last_updated":sensor_temps_and_hums[rooms_info[room_id]['sensor']]['last_updated']
                    }
            else:
                room_temps_and_hums[room_id] = {"temp":"none","hum":"none","last_updated":"none"}
        
        return room_temps_and_hums
    except ModuleException:
        raise ModuleException("couldn't read sensor state due to", severity = 2)
    except Exception:
        raise ModuleException("unexpected error while reading sensor state", severity = 2)
#endregion

#region Config
"""Utility functions related to config."""

def get_rooms_info():
    return get_system_config("rooms")

def get_cycles_info():
    return get_system_config("cycles")

def get_system_config(subdict_key: str):
    system = load_json_to_dict(os.path.join('config', 'system.json'))
    return system[subdict_key]

#endregion

#region Misc
"""
All sorts of utility functions and shorthands.
"""

def get_project_root():
    """
    Returns the root of the project as a string.
    """
    try:
        current_file_path = os.path.abspath(__file__)
        parent_directory_path = os.path.dirname(current_file_path)
        return os.path.dirname(parent_directory_path)
    except OSError:
        raise ModuleException("couldn't get project root due to")
    except Exception:
        raise ModuleException("unexpected error when getting project root")

def timestamp():
    return datetime.now().strftime(settings.get('timestamp_format'))

def load_json_to_dict(relative_path:str):
    try:
        project_root = get_project_root()

        with open(os.path.join(project_root, relative_path), 'r', encoding='utf-8') as file:
            loaded_dict = json.load(file)
            
        return loaded_dict
    except Exception:
        raise ModuleException(f"unexpected error while loading {relative_path} to dict")


#endregion

#endregion