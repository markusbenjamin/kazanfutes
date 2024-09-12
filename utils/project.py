#region Imports
import json
import logging
import os
import time
import traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

import filelock

#endregion

#region Classes

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
        settings_file = os.path.join(project_root, 'system_config', 'settings.json')
        self.settings = {}
        self.load_settings_from_file(settings_file)

    def load_settings_from_file(self, settings_file):
        """Load settings from a JSON file."""
        try:
            with open(settings_file, 'r') as file:
                self.settings = json.load(file)
        except FileNotFoundError as e:
            raise ProjectSettingError(f"Settings file {settings_file} not found.", original_exception=e, include_traceback=True) from e
        except json.JSONDecodeError as e:
            raise ProjectSettingError(f"Invalid JSON format in {settings_file}.", original_exception=e, include_traceback=True) from e
        except Exception as e:
            raise ProjectSettingError(f"An unexpected error occurred while loading the settings file: {e}", original_exception=e, include_traceback=True) from e

    def get(self, key):
        """Retrieve a setting value, or None if the key does not exist."""
        try:
            return self.settings.get(key)
        except Exception as e:
            raise ProjectSettingError(f"Error accessing the setting '{key}': {e}", original_exception=e, include_traceback=True) from e

    def set(self, key, value):
        """Modify or add a setting."""
        try:
            self.settings[key] = value
        except Exception as e:
            raise ProjectSettingError(f"Error setting the value for '{key}': {e}", original_exception=e, include_traceback=True) from e
    
settings = Settings()
#endregion

#region Exception hierarchy
# Base Exception
class HeatingControlError(Exception):
    """Base exception for all heating system """
    def __init__(self, message, original_exception=None, include_traceback=False):
        # Store the original exception, if provided
        self.original_exception = original_exception
        
        # Optionally include the traceback
        if include_traceback and original_exception is not None:
            message += f"\nTraceback:\n{traceback.format_exc()}"
        
        report(message)

        # Initialize the base Exception with the final message
        super().__init__(message)

# Data Management Errors
class DataManagementError(HeatingControlError):
    """Base exception for data management-related """
    pass

class GitOperationError(DataManagementError):
    """Raised when a Git operation fails."""
    pass

# DeCONZ Module Errors
class DeconzError(HeatingControlError):
    """Base exception for DeCONZ-related """
    pass

class DeconzSetupError(DeconzError):
    """Raised for errors during Deconz setup (such as API key generation, URL read in, etc.)."""
    pass

class DeconzReadError(DeconzError):
    """Raised for errors while trying to get data from the ZigBee mesh."""
    pass

# I/O Errors
class ProjectIOError(HeatingControlError): #Named so it won't interfere with the native IOError class.
    """Base exception for I/O-related """
    pass

# Communication Errors
class CommunicationError(HeatingControlError):
    pass

class GMailError(CommunicationError):
    pass

# Project Errors
class ProjectError(HeatingControlError):
    """Base exception for project-wide """
    pass

class ProjectConfigError(ProjectError):
    """Raised when configuration file operations fail (e.g., reading rooms.json)."""
    pass

class ProjectSettingError(ProjectError):
    """Raised when issues with settings arise."""
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
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
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
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError) as e:
        raise GMailError("Failed to authenticate with Gmail SMTP server or unsupported operation.", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
        raise GMailError("SMTP issue: Recipient or sender refused, or data error occurred.", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise GMailError(f"An unexpected error occurred while sending an email: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    
    return success

def init_logger(log_file_path: str):
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
    full_log_path = os.path.join(get_project_root(),'data','logs', log_file_path)
    log_directory = os.path.dirname(full_log_path)
    if not os.path.exists(log_directory):
        os.makedirs(log_directory, exist_ok=True)

    handler = TimedRotatingFileHandler(full_log_path, when='midnight', interval=1)
    
    # Define formatter with timestamp
    formatter = logging.Formatter(f'%(message)s')
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def log(data: dict):
    """
    Used for runtime logging.
    Logs the provided data to a JSON log file in a hardcoded directory, named after the script calling this function.
    
    Args:
        data (dict): The data to be logged.
    """
    import inspect
    from pathlib import Path

    # Get the name of the calling script (the file that called log())
    calling_script = os.path.basename(inspect.stack()[1].filename).split('.')[0]

    # Hardcoded log directory
    log_directory = os.path.join('services')
    
    # Create the log directory if it doesn't exist
    Path(log_directory).mkdir(parents=True, exist_ok=True)
    
    # Full path to the log file
    log_file_path = os.path.join(log_directory, f'{calling_script}.json')
    
    # Initialize the logger and log the data
    log_data(data,log_file_path)

def log_data(data: dict, log_file_path: str):
    """
    Used for feature logging.
    Logs the provided data to a specified log file.
    
    Args:
        data (dict): The data to be logged.
        log_file_path (str): The full path to the log file.
    """
    # Initialize the logger and log the data
    init_logger(log_file_path)
    logger = logging.getLogger()
    log_entry = {'timestamp': datetime.now().strftime(settings.get('timestamp_format'))}
    log_entry.update(data)  # Add the rest of the data
    logger.info(json.dumps(log_entry))

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
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise GitOperationError(f"Failed to change directory to {project_dir_path}: {e}", original_exception = e, include_traceback = settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise GitOperationError(f"Unexpected error while changing directory: {e}", original_exception = e, include_traceback = settings.get('detailed_error_reporting')) from e

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
    except subprocess.CalledProcessError as e:
        raise GitOperationError(f"Git command failed: {e}") from e
    except Exception as e:
        raise GitOperationError(f"Unexpected error while pushing {project_dir_path} to repo: {e}", original_exception = e, include_traceback = settings.get('detailed_error_reporting')) from e
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
    except FileNotFoundError as e:
        raise DeconzSetupError("No deconz_api_url file in secrets_and_env.", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise DeconzSetupError(f"An unexpected error occurred while reading deconz_api_url: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e

    deconz_api_key = ""
    try:
        with open(f'{project_root}/secrets_and_env/deconz_api_key', 'r') as file:
            deconz_api_key = file.read()
    except FileNotFoundError as e:
        raise DeconzSetupError("No deconz_api_key file in secrets_and_env.", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise DeconzSetupError(f"An unexpected error occurred while reading deconz_api_key: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e

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
        raise DeconzSetupError("Missing Deconz API URL at secrets_and_env", original_exception=None, include_traceback=False)
    
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
     ) as e:
        raise DeconzSetupError(f"Failed to connect to Deconz API: {e}") from e
    except Exception as e:
        raise DeconzSetupError(f"An unexpected error occurred while connecting to Deconz API: {e}") from e

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
        raise DeconzSetupError("Couldn't extract Deconz URL.", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise DeconzSetupError(f"An unexpected error occurred while extracting Deconz URL: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting'))  from e
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
     ) as e:
        raise DeconzReadError(f"Failed to connect to Deconz API due to client or network error: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise DeconzReadError(f"Failed to connect to Deconz API due to unexpected error:{e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e

def read_sensors():
    """
    Extracts sensor states from overall ZigBee mesh state.
    """
    return read_deconz_state().sensors.items()
#endregion

#region Error management
def error_registrar(exception_type, severity, origin = None, origin_timestamp = None):
    """
    Registers a new error in error_registry.json if not already present and the file is not locked.
    If error_registry.json is locked, appends the error to error_buffer.json for later retry.
    Automatically sets default values for metadata (reported, timestamps, etc.).
    
    Parameters:
    exception_type (str): Type of the raised exception, preferably from the project-specific exception hierarchy.
    severity (str): Severity level of the error (1 := low, 2 := moderate, 3 :=high).
    origin (str): Where the error originated (e.g., file, function, line).
    origin_timestamp (str): Timestamp when the error occurred.

    Returns true only if an error has been registered into the error registry, false otherwise.
    """

    # Define the hardcoded paths to the error registry and buffer using the absolute project root
    ERROR_REGISTRY_PATH = f"{get_project_root()}/data/errors/error_registry.json"
    ERROR_BUFFER_PATH = f"{get_project_root()}/data/errors/error_buffer.json"
    
    error_entry = {
        "exception_type": exception_type, 
        "severity": severity,
        "origin": generate_exception_origin_stamp() if origin is None else origin,
        "origin_timestamp": time.strftime(settings.get('timestamp_format') if origin_timestamp is None else origin_timestamp),
        "registration_timestamp": None,
        "reported": False,
        "reported_timestamp": None,
        "checked": False,
        "checked_timestamp": None
    }

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
                if (existing_error["exception_type"] == error_entry["exception_type"] and
                    existing_error["severity"] == error_entry["severity"] and
                    existing_error["origin"] == error_entry["origin"]):
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

def generate_exception_origin_stamp():
    """
    Generates a unique origin string for the calling script, with the full call chain from the 
    innermost function to the main scope, as well as the file name and line number.
    
    Returns:
        str: A string representing the origin of the exception in the calling script, 
             including the full call chain.
    """
    # Get the current stack trace
    stack = traceback.extract_stack()

    # Initialize the call chain with an empty list
    call_chain = []
    
    # Traverse the stack frames from the bottom up (skip the last frame, which is this function)
    for frame in stack[:-2]:
        # Get function name, or "main scope" if in the global scope
        function_name = frame.name if frame.name != "<module>" else "main_scope"
        call_chain.append(function_name)

    # Join the call chain to form a string
    full_call_chain = "/".join(call_chain)

    # Get the last relevant frame (before this function was called)
    tb = stack[-3] if len(stack) >= 3 else stack[-1]

    # Extract the script name, line number, and function name
    script_name = os.path.basename(tb.filename)
    line_number = tb.lineno

    # Create a unique origin string based on file, call chain, and line number
    origin = f"{script_name}:{full_call_chain}:{line_number}"
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
    except (
        DeconzError,
        ProjectError
     ) as e:
        raise ProjectIOError(f"Couldn't read sensor state due to: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise ProjectIOError(f"Unexpected error while reading sensor state: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
#endregion

#region Project and system config
"""File and folder management, etc."""

def get_project_root():
    """
    Returns the root of the project as a string.
    """
    try:
        current_file_path = os.path.abspath(__file__)
        parent_directory_path = os.path.dirname(current_file_path)
        return os.path.dirname(parent_directory_path)
    except OSError as e:
        raise ProjectError(f"Couldn't get project root due to: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise ProjectError(f"Unexpected error when getting project root: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e

def get_rooms_info():
    try:
        project_root = get_project_root()

        with open(os.path.join(project_root, 'system_config', 'rooms.json'), 'r') as file:
            rooms_dict = json.load(file)
            
        return rooms_dict
    except (
        FileNotFoundError,PermissionError,json.JSONDecodeError,OSError
    ) as e:
        raise ProjectConfigError(f"Couldn't get rooms config due to: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e
    except Exception as e:
        raise ProjectConfigError(f"Unexpected error while reading rooms config: {e}", original_exception=e, include_traceback=settings.get('detailed_error_reporting')) from e

#endregion

#endregion