"""
Common toolkit for the entire project.
Import with: from utils.project import *
"""

#region Imports
import asyncio
import csv
import json
import logging
import math
import os
import random
import subprocess
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
import google.auth
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

on_raspi = False
if os.name == 'posix':
    on_raspi = True

import aiohttp
import filelock
import requests
import pytz
from PIL import Image

if on_raspi:
    import RPi.GPIO as GPIO
    GPIO.setwarnings(False)
    import tinytuya
    from pydeconz.gateway import DeconzSession
    import tzlocal

#endregion

#region Settings
def initialize_settings():
    """
    Brittle function to initialize the settings dict. Do not use anywhere except directly below.
    """
    try:
        current_file_path = os.path.abspath(__file__)
        parent_directory_path = os.path.dirname(current_file_path)
        project_root = os.path.dirname(parent_directory_path)
        with open(os.path.join(project_root, 'utils/settings.json'), 'r', encoding='utf-8') as file:
            settings_dict = json.load(file)            
        return settings_dict
    except Exception as e:
        print(f"Can't load settings due to {e}")
    
settings = initialize_settings()
settings['on_raspi'] = on_raspi

#endregion

#region Function definitions

#region Comms
"""Everything related to external communication and reporting."""

#region Console
def report(message, *, verbose = False):
    """Generalized output plug for runtime messages and reporting."""
    if verbose: # Verbose is true for messages that should only be printed in verbose mode.
        if settings['verbosity']:
            print(message)
    else:
        print(message)
#endregion

#region Email
def notify_admin():
    pass

def send_email(to, subject='', body=''):
    """
    Sends an email using Gmail's SMTP server. Login credentials are loaded from 
    project_root/config/secrets_and_env/gmail_login.
    
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
    login_file_path = os.path.join(get_project_root(), 'config','secrets_and_env', 'gmail_login')

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
#endregion

#region Logging
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
    relative_log_file_path = os.path.join('service_execution', f'{calling_script_name}/{calling_script_name}.json')
    
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

#region Firebase
def default_firebase_callback(relative_path, node_changes):
    """
    Default callback function for the JSONNodeAtURL class 
    (hardcoded to represent Firebase, but easily adapted to other JSON nodes).
    """
    report(f"Callback: data changed: {node_changes} at 'Firebase/{relative_path}'.")
    return {'path':relative_path,'data':node_changes}

class JSONNodeAtURL:
    def __init__(self, node_relative_path:str='', url:str = ''):
        """
        Initialize with the URL of a freely accessible JSON stored at an URL.
        Hardcoded to represent Firebase, but easily adapted to other JSON nodes.
        :param node_relative_path: The path to the node relative to the root of the database.
        :param url: The URL of the root of the database, set to the Firebase Realtime Database address defined in settings by default. 
        """
        
        self.node_relative_path = node_relative_path
        self.url = (settings["firebase_url"] if url == '' else url)+"/"+node_relative_path
        self.last_known_state_of_node = self.read()
        self.last_sent_data = None

    def interact(self, method, subpath:str = '', **kwargs):
        """
        Unified method for all kinds of requests. Do not use on its own.
        """
        response = None
        try:
            response = method(self.url+"/"+subpath+".json",**kwargs)
            response.raise_for_status()
            report(f"Successfully interacted with node '{self.node_relative_path}' via {method.__name__}.", verbose = True)
            if method.__name__ == 'get':
                return jsonify_array(response.json())
        except Exception:
            if response:
                report(f"Failed to interact with node via {method.__name__}. Status code: {response.status_code}", verbose = True)
                raise ModuleException(f"failed to interact with node '{self.node_relative_path}' via {method.__name__}")
            else:
                report(f"Failed to interact with node via {method.__name__}, response is not even initialized.", verbose = True)
                raise ModuleException(f"failed to interact with node '{self.node_relative_path}' via {method.__name__}")

    def read(self, read_subpath:str = ''):
        """
        Read and return data from the node at specified subpath.
        """
        return self.interact(requests.get, subpath = read_subpath)

    def overwrite(self, data:dict, overwrite_subpath:str = ''):
        """
        Overwrite data on node at specified subpath.
        """
        self.last_sent_data = {'path':overwrite_subpath,'data':data}
        self.interact(requests.put, subpath = overwrite_subpath, json = data)

    def write(self, data:dict, write_subpath:str = ''):
        """
        Update specific fields in the node without overwriting the entire node.
        """
        self.last_sent_data = {'path':write_subpath,'data':data}
        self.interact(requests.patch, subpath = write_subpath, json = data)

    def delete(self):
        """
        Deletes the entire node. Use with caution.
        """
        self.interact(requests.put, subpath = '', json = {})

    def poll_periodically(self, interval=5, callback = default_firebase_callback):
        """
        Starts a background thread to periodically check for changes in the node's data.
        If change is detected, calls the callback.
        The callback gets passed the relative path of the node and the list of node paths changed with their new content.
        """
        self._stop_listening = False
        thread = threading.Thread(target=self._listen_loop, args=(interval,callback,))
        thread.daemon = True  # Daemonize thread so it exits when main program exits
        thread.start()

    def _listen_loop(self,  interval=5, callback = default_firebase_callback):
        """
        The internal loop that checks for data changes.
        This function runs in a separate thread when poll_periodically is called.
        """
        while not self._stop_listening:
            current_state_of_node = self.read()
            try:
                if current_state_of_node != self.last_known_state_of_node:
                    node_changes = compare_dicts(self.last_known_state_of_node,current_state_of_node)
                    self.last_known_state_of_node = current_state_of_node
                    node_change_data = []
                    for change in node_changes:
                        for key, value in change.items():
                            if '/' in key:
                                path, data_key = key.rsplit('/', 1)
                            else:
                                path = ''
                                data_key = key
                            changed_data = {'path': path, 'data': {data_key: value}}
                            if self.last_sent_data != changed_data:
                                node_change_data.append(changed_data)
                    if 0<len(node_change_data):
                        callback(self.node_relative_path, node_change_data)
            except:
                raise ModuleException(f'unexpected error with periodical polling on node {self.node_relative_path}')
            time.sleep(interval)

    def stop_listening(self):
        """
        Stops the periodical polling thread.
        """
        self._stop_listening = True
        report("Listener stopped.",verbose=True)

#endregion

#region GitHub

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

#endregion

#region Error management
def faulty_module_function():
    """
    For testing purposes.
    """
    try:
        1/0
    except Exception:
        raise ModuleException("something went wrong in module")

class ServiceException(Exception):
    """
    Exception class that calls the error registrar when constructor is intialized (except when testing == True),
    should only be instantiated (but not necessarily raised) in service scripts.
    """
    def __init__(self, message, original_exception = None, severity = 0):
        """
        Generates and registers error entry.
        """
        error_entry = {}
        
        register = True

        try: # If called by a raised exception
            exception_details = extract_exception_details()
            if exception_details['type'] == 'KeyboardInterrupt':
                register = False
            else:
                error_entry['message'] = message +': '+exception_details['message']+'.'
                if exception_details['type'] == 'ModuleException':
                    error_entry['severity'] = max(severity, original_exception.severity)
                else:
                    error_entry['severity'] = severity
                error_entry['origin'] = exception_details['origin']

        except Exception as e: # If called on it's own (unlikely)
            if isinstance(e, KeyboardInterrupt):
                register = False
            else:
                error_entry['message'] = message
                error_entry['severity'] = severity
                error_entry['origin'] = generate_call_origin()
        error_entry['origin_timestamp'] = timestamp()
        if settings['dev']:
            report(json.dumps(error_entry, indent=4))
        elif register:
            error_registrar(error_entry)
        super().__init__(message)

class ModuleException(Exception):
    """
    Custom module exception with proposed severity level and origin details.

    Should only be raised in module functions.
    """
    def __init__(self, message, severity=0):
        caller_details = extract_exception_details()
        self.severity = severity
        if caller_details:
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
    ERROR_REGISTRY_PATH = os.path.join(get_project_root(), "data", "error_management", "error_registry.json")
    ERROR_BUFFER_PATH = os.path.join(get_project_root(), "data", "error_management", "error_buffer.json")
    
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
                error_entry["registration_timestamp"] = timestamp()
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
            filename = tb.tb_frame.f_code.co_filename.split(os.sep)[-1]
            scope = tb.tb_frame.f_code.co_name or 'main_scope'
            line = tb.tb_lineno
            origin_chain.append(f"{filename}{'/'+scope if scope != '<module>' else ''}:{line}")
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

#region Wrappers
"""Wrapper functions for everything IO."""

def generate_and_save_cycle_crops(relative_path:str, crop_rectangles:list, del_original_on_success:bool = True):
    """
    Generates, saves and returns the crop for each cycle from a passed Pillow image.
    """
    try:
        image = load_image(relative_path)

        capture_timestamp = os.path.splitext(os.path.basename(relative_path))[0]

        daystamp = datetime.strptime(capture_timestamp,settings["timestamp_format"]).strftime("%Y-%m-%d")
        hourminute_stamp = datetime.strptime(capture_timestamp,settings["timestamp_format"]).strftime("%H-%M")
        
        image = image.rotate(90, resample=Image.BICUBIC, expand=True) # Rotate with antialiasing
        cycle_crops = []

        for cycle in range(1, 5):
            cropped_img = image.crop(crop_rectangles[cycle - 1])
            cycle_crops.append(cropped_img)
            save_relative_path = os.path.join('data','logs','heat_delivery',f"heatmeter_images_{daystamp}",f"{hourminute_stamp}_{cycle}.png")
            save_image(cropped_img, save_relative_path)

        if del_original_on_success:
            delete_image(relative_path)

        return cycle_crops           

    except Exception:
        raise ModuleException(f"couldn't extract cycle crops for {capture_timestamp}")

def get_boiler_state():
    """
    Returns either 0 or 1 after reading the specified GPIO pin for the boiler.
    """
    try:
        return read_pin_state(get_system_setup()['boiler']['GPIO'])
    except Exception:
        raise ModuleException(f"couldn't read boiler state")

def set_boiler_state(state:int):
    """
    Sets the state of the boiler via GPIO interfacing.
    Returns success.
    """
    success = False
    try:
        set_pin_mode(get_system_setup()['boiler']['GPIO'],GPIO.OUT)
        success = set_pin_state(get_system_setup()['boiler']['GPIO'],state)
    except Exception:
        raise ModuleException(f"couldn't turn boiler {['OFF','ON'][state]}")
    return success

def get_pump_states():
    """
    Returns a dict with 0 or 1 or None if cannot read for each pump.
    """
    try:
        state = {'1':None,'2':None,'3':None,'4':None}
        pump_info = get_pumps_info()
        for pump,info in pump_info.items():
            state[pump] = get_pump_state(pump)
        return state
    except Exception:
        raise ModuleException(f"couldn't read pump states")

def get_pump_state(pump:str):
    """
    Returns a faux val for development purposes for now.
    """
    try:
        device = connect_to_pump(pump)
        if device:
            return int(device.status()['dps']['1']) # This path encodes the on/off state in the JSON reply
    except Exception:
        raise ModuleException(f"couldn't read state of pump {pump}")

def set_pump_state(pump:str,state:int):
    """
    Sets the state of a given pump via Tuya interfacing.
    Warning: returns success not state.
    """
    success = False
    try:
        device = connect_to_pump(pump)
        if device:
            if state:
                success = device.turn_on()['dps']['1']
            else:
                success = device.turn_off()['dps']['1'] == False
    except Exception:
        raise ModuleException(f"couldn't turn pump {pump} {['OFF','ON'][state]}")
    return success

def set_all_pumps(state:int):
    """
    Turn all pumps on or off at once. Returns a dict of successes (and __not__ states!).
    """
    success = {"1":False,"2":False,"3":False,"4":False}
    try:
        pump_info = get_pumps_info()
        for pump,info in pump_info.items():
            success[pump] = set_pump_state(pump,state)
    except Exception:
        raise ModuleException(f"couldn't turn all pumps {['OFF','ON'][state]}")
    return success

def shutdown_heating():
    """
    Turns off all pumps & boiler. Returns success.
    """
    success = False
    try:
        set_boiler_state(0)
        set_all_pumps(0)
        success = True
    except Exception:
        raise ModuleException(f"couldn't shut down heating")
    return success

def get_room_temps_and_humidity_dev():
    """
    Returns a faux dict for development purposes.
    """
    rooms_info = get_rooms_info()
    room_temps_and_hums = {}
    for room in rooms_info:
        if rooms_info[room]['sensor']:
            room_temps_and_hums[room] = {
                "temp":1600,
                "hum":5000,
                "last_updated":datetime.now().strftime(settings['timestamp_format'])
                }
        else:
            room_temps_and_hums[room] = {
                "temp":None,
                "hum":None,
                "last_updated":None
                }
    return room_temps_and_hums

def get_room_temps_and_humidity():
    """
    Returns dated temperature and humidity readings for all rooms in config.
    """

    try:
        sensors_state = read_sensors()

        sensor_temps_and_hums = {}
        for sensor_id, sensor in sensors_state:
            last_updated = datetime.strptime(sensor.raw['state']['lastupdated'], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=pytz.UTC).astimezone(tzlocal.get_localzone()).strftime(settings['timestamp_format'])
            if sensor.type == "ZHATemperature":
                if sensor.name not in sensor_temps_and_hums:
                    sensor_temps_and_hums[sensor.name] = {'temp':'none','hum':'none','last_updated':'none'}
                sensor_temps_and_hums[sensor.name]['temp'] = sensor.temperature
                sensor_temps_and_hums[sensor.name]['last_updated'] = last_updated
            elif sensor.type == "ZHAHumidity":
                if sensor.name not in sensor_temps_and_hums:
                    sensor_temps_and_hums[sensor.name] = {'temp':None,'hum':None,'last_updated':None}
                sensor_temps_and_hums[sensor.name]['hum'] = sensor.humidity
                sensor_temps_and_hums[sensor.name]['last_updated'] = last_updated

        rooms_info = get_rooms_info()

        room_temps_and_hums = {}
        for room in rooms_info:
            if rooms_info[room]['sensor'] in sensor_temps_and_hums:
                room_temps_and_hums[room] = {
                    "temp":sensor_temps_and_hums[rooms_info[room]['sensor']]['temp'],
                    "hum":sensor_temps_and_hums[rooms_info[room]['sensor']]['hum'],
                    "last_updated":sensor_temps_and_hums[rooms_info[room]['sensor']]['last_updated']
                    }
            else:
                room_temps_and_hums[room] = {"temp":None,"hum":None,"last_updated":None}
        
        return room_temps_and_hums
    except ModuleException:
        raise ModuleException("couldn't read sensor state due to", severity = 2)
    except Exception:
        raise ModuleException("unexpected error while reading sensor state", severity = 2)

#endregion

#region PIL and fswebcam
"""
PIL image handling library interfacing with image capture using fswebcam.
"""
def load_image(relative_path):
    """
    Loads and returns an image file using Pillow.
    Path should be relative to project root.
    """
    try:
        full_path = os.path.join(get_project_root(),relative_path)
        with Image.open(full_path) as img:
            img.load()
            return img
    except:
        raise ModuleException(f"couldn't open image at {relative_path}")
    
def save_image(image, relative_path):
    """
    Saves an image file as PNG or JPG using Pillow.
    Automatically determines the format based on the file extension.
    Path should be relative to project root.
    """
    try:
        full_path = os.path.join(get_project_root(), relative_path)

        directory = os.path.dirname(full_path)
        if not os.path.exists(directory):
            os.makedirs(directory)
        
        extension = relative_path.lower().split('.')[-1]  # Get file extension
        
        if extension == 'jpg' or extension == 'jpeg':
            image = image.convert('RGB')  # Pillow requires RGB mode for JPEG
            image.save(full_path, format='JPEG')
            return relative_path
        elif extension == 'png':
            image.save(full_path, format='PNG')
            return relative_path
        else:
            raise ModuleException(f"unsupported file format for {relative_path}")
    
    except Exception:
        raise ModuleException(f"couldn't save image to {relative_path}")

def delete_image(relative_path):
    """
    Deletes an image file.
    Path should be relative to project root.
    """
    try:
        full_path = os.path.join(get_project_root(), relative_path)
        
        if os.path.exists(full_path):
            os.remove(full_path)
        else:
            raise ModuleException(f"image at {relative_path} does not exist")
    
    except Exception:
        raise ModuleException(f"couldn't delete image at {relative_path}")

def capture_image_to_disk(relative_path:str):
    """
    Uses fswebcam to capture an image using the first accessible webcam,
    then saves it to the relative project path given as a timestamped jpg.
    """
    full_path = os.path.join(get_project_root(),relative_path)
    if not os.path.exists(full_path):
        os.makedirs(full_path)
    
    image_filename = f'{timestamp()}.jpg'
    full_save_path = os.path.join(full_path,image_filename)
    relative_save_path = os.path.join(relative_path,image_filename)
    
    try:
        subprocess.run(['fswebcam', '-r', '1280x720', '--no-banner', full_save_path])
        report(f'Captured image {image_filename}.',verbose=True)
        return relative_save_path
    except Exception:
        raise ModuleException(f"couldn't capture and save image to {relative_save_path}")
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
        with open(f'{project_root}/config/secrets_and_env/deconz_api_url', 'r') as file:
            deconz_api_url = file.read()
    except FileNotFoundError:
        raise ModuleException("no deconz_api_url file in secrets_and_env")
    except Exception:
        raise ModuleException("an unexpected error occurred while reading deconz_api_url",severity=2)

    deconz_api_key = ""
    try:
        with open(f'{project_root}/config/secrets_and_env/deconz_api_key', 'r') as file:
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
            with open(f'{project_root}/config/secrets_and_env/deconz_api_key', 'w') as file:
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

#region Tuya
"""
Tuya interfacing.
"""
def connect_to_pump(pump:str):
    """
    Connects to a pump via tinytuya and returns an OutletDevice object if successful.
    Returns None if cannot connect to pump.
    """
    try:
        pump_info = get_pumps_info()
        device = tinytuya.OutletDevice(
            dev_id = pump_info[pump]['id'],
            address = pump_info[pump]['ip'],      # Or set to 'Auto' to auto-discover IP address
            local_key = pump_info[pump]['key'], 
            version = 3.3)
        return device
    except Exception:
        raise ModuleException(f"couldn't connect to pump {pump}")

def transfer_vals_from_devices_and_snapshot_jsons_to_system_json():
    """
    To automatize transfer of id, ip and local key vals. Maybe later.
    """
    pass
#endregion

#region GPIO
"""
GPIO interfacing.
"""

#region Mock GPIO class so module file loads in Windows too
if not on_raspi:
    class GPIO:
        # Constants
        OUT = "OUT"
        IN = "IN"
        HIGH = 1
        LOW = 0
        PUD_OFF = "PUD_OFF"
        PUD_DOWN = "PUD_DOWN"
        PUD_UP = "PUD_UP"
        BCM = "BCM"
        
        # Mock functions
        @staticmethod
        def setmode(mode):
            print(f"GPIO setmode({mode}) called.")
        
        @staticmethod
        def setup(pin, mode, pull_up_down=None):
            print(f"GPIO setup(pin={pin}, mode={mode}, pull_up_down={pull_up_down}) called.")
        
        @staticmethod
        def output(pin, state):
            print(f"GPIO output(pin={pin}, state={state}) called.")
        
        @staticmethod
        def input(pin):
            print(f"GPIO input(pin={pin}) called.")
            return GPIO.LOW  # Default to LOW for testing
        
        @staticmethod
        def cleanup():
            print("GPIO cleanup() called.")

#endregion

def load_GPIO_state(pin:int = None):
    GPIO_state = load_json_to_dict('system/GPIO_state.json')
    pin_key = str(pin)
    if isinstance(pin,str):
        pin = int(pin)
    if pin and pin_key not in GPIO_state:
        GPIO_state[pin_key] = {}
    return GPIO_state

def save_GPIO_state(GPIO_state:dict):
    return export_dict_as_json(GPIO_state,'system/GPIO_state.json')

def release_pin(pin:int):
    """
    Sets a GPIO pin to IN with no pull-down state set and removes it from GPIO setup.
    """
    pin_key = str(pin)
    if isinstance(pin,str):
        pin = int(pin)
    set_pin_mode(pin, GPIO.IN)
    GPIO_state = load_GPIO_state()
    GPIO_state.pop(pin_key,None)
    save_GPIO_state(GPIO_state)

def reset_GPIO():
    """
    Releases all GPIO pins.
    """
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO_state = load_GPIO_state()

        for pin in GPIO_state.keys():
            release_pin(pin)
    except Exception:
        raise ModuleException(f"couldn't reset GPIO setup")

def set_pin_mode(pin: int, mode, pud=GPIO.PUD_OFF):
    """
    Sets a GPIO pin's mode and the state of it's internal pull-down resistor.
    Mode: either GPIO.IN or GPIO.OUT
    Pud: for IN pins floating (PUD_OFF) if not specified, or either GPIO.PUD_UP or GPIO.PUD_DOWN. Do not specify for OUT pins.
    """
    pin_key = str(pin)
    if isinstance(pin,str):
        pin = int(pin)
    try:
        GPIO.setmode(GPIO.BCM) # Follows the pin naming convention written on the mother- and breadboard

        GPIO_state = load_GPIO_state(pin)

        GPIO_state[pin_key]['mode'] = "IN" if mode == GPIO.IN else "OUT"
        if mode == GPIO.OUT and pud != GPIO.PUD_OFF:
            report(f'Warning: trying to set PUD {"UP" if pud == GPIO.PUD_UP else "DOWN"} for OUT pin {pin}. Aborting operation.')
            return
        
        GPIO.setup(pin, mode, pud)
        GPIO_state[pin_key]['pud'] = "OFF" if pud == GPIO.PUD_OFF else "UP" if pud == GPIO.PUD_UP else "DOWN"
        if mode == GPIO.IN:
            GPIO_state[pin_key].pop("state",None)
        
        save_GPIO_state(GPIO_state)
    except Exception:
        raise ModuleException(f"couldn't set pin {pin} mode to {'IN' if mode == GPIO.IN else 'OUT'}")

def set_pin_state(pin:int, state:int):
    """
    Sets the specified GPIO OUT pin to the given state (HIGH or LOW).
    Saves the setting externally.
    """
    pin_key = str(pin)
    if isinstance(pin,str):
        pin = int(pin)
    success = False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO_state = load_GPIO_state(pin)        

        if 'mode' not in GPIO_state[pin_key].keys():
            report(f"Trying to set uninitialized pin {pin} to {['LOW','HIGH'][state]}. Set mode first. Aborting operation.")
            return
        if GPIO_state[pin_key]['mode'] == 'IN':
            report(f"Warning: trying to set state {state} for IN pin {pin}. Aborting operation.")
            return
        
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH if state == 1 else GPIO.LOW)
        GPIO_state[pin_key]['state'] = "HIGH" if state == 1 else "LOW"
        save_GPIO_state(GPIO_state)
        success = True
    except Exception:
        raise ModuleException(f"couldn't set pin {pin} to {['LOW','HIGH'][state]}")
    return success

def read_pin_state(pin:int):
    """
    Reads the state of the specified GPIO pin.
    """
    pin_key = str(pin)
    if isinstance(pin,str):
        pin = int(pin)
    try:
        GPIO.setmode(GPIO.BCM)
        
        GPIO_state = load_GPIO_state(pin)

        if 'mode' not in GPIO_state[pin_key].keys():
            return 0
        set_pin_mode(
            pin,
            GPIO.OUT if GPIO_state[pin_key]['mode']=='OUT' else GPIO.IN,
            GPIO.PUD_OFF if GPIO_state[pin_key]['pud'] == "OFF" else GPIO.PUD_UP if GPIO_state[pin_key]['pud'] == GPIO.PUD_UP else GPIO.PUD_DOWN
            )
        state = GPIO.input(pin)
        return state
    except Exception:
        raise ModuleException(f"couldn't read state of GPIO pin {pin}")

#endregion

#endregion

#region Config
"""Utility functions related to config."""

def get_rooms_info():
    return get_system_setup("rooms")

def get_cycles_info():
    return get_system_setup("cycles")

def get_pumps_info():
    pumps_info = {}
    for cycle,info in get_cycles_info().items():
        pumps_info[cycle] = info['pump']
    return pumps_info

def get_system_setup(subdict_key: str=''):
    system = load_json_to_dict(os.path.join('system', 'setup.json'))
    return system if subdict_key == '' else system[subdict_key]

def room_to_cycle(room):
    if not isinstance(room,str):
        room = str(room)
    rooms_info = get_rooms_info()
    return rooms_info[room]['cycle']

def room_num_to_name(room):
    if not isinstance(room,str):
        room = str(room)
    rooms_info = get_rooms_info()
    return rooms_info[room]['name']

def room_name_to_num(room_name):
    rooms_info = get_rooms_info()
    for key,val in rooms_info.items():
        if val['name'] == room_name:
            return key
    report("Couldn't find room name in system.")
    return None

def cycle_to_rooms(cycle):
    if not isinstance(cycle,str):
        cycle = str(cycle)
    cycles_info = get_cycles_info()
    return cycles_info[cycle]['rooms']

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
    except Exception:
        raise ModuleException("couldn't get project root due to")

def sign(num):
    """
    Returns the sign of a number.
    """
    return (num > 0) - (num < 0)

#region Time
def timestamp(datetime_object:datetime = datetime.now()):
    """
    Returns a timestamp string with the format specified in settings.
    """
    return datetime_object.strftime(settings['timestamp_format'])

def generate_timepoint_info(timepoint = datetime.now()):
    """
    If no arguments supplied generate for now, else for datetime or timestamp string.
    Returns dict with keys: unix_day, month, day_of_week, weekday, timestamp, datetime_object.
    """
    if isinstance(timepoint,datetime) or isinstance(timepoint,str):
        if isinstance(timepoint,str):
            timepoint = timestamp_to_datetime(timepoint)
        unixtime = timepoint.timestamp()
        unix_day = math.floor(unixtime/(60*60*24))
        unix_hour_of_day = math.floor(unixtime/(60*60))-unix_day*24
        datetime_hour_of_day = timepoint.hour
        unix_to_datetime_hour_shift = (24 + datetime_hour_of_day - unix_hour_of_day)%24
        unixtime = timepoint.timestamp() + unix_to_datetime_hour_shift*60*60
        timepoint_inf = {
            'unix_day':math.floor(unixtime/(60*60*24)),
            'hour_of_day':timepoint.hour,
            'month':timepoint.month,
            'day_of_week':timepoint.weekday()+1,
            'weekday': True if timepoint.weekday()+1<6 else False,
            'timestamp':timepoint.strftime(settings["timestamp_format"]),
            'datetime_object':timepoint
        }
        return timepoint_inf
    else:
        report('Invalid timepoint input.')

def timestamp_to_datetime(timestamp:str):
    """
    Turns a timestamp string into a datetime object for internal Python manipulation.
    """
    return datetime.strptime(timestamp,settings['timestamp_format'])
#endregion

#region JSON and dicts
def find_val_in_dict(nested_dict, value):
    """
    Returns the paths to the occurences of a value in a nested dict.
    """
    paths = []
    
    def find_in_subdict(subdict, path):
        if isinstance(subdict, dict):
            for key, item in subdict.items():
                find_in_subdict(item, path + [key])
        elif subdict == value:
            paths.append(path)
    
    find_in_subdict(nested_dict, [])
    return ['/'.join(path_list) for path_list in paths]

def response_table_to_dict_list(response_table, header = None):
    """
    Generates a list of dicts from a response table generated by Google Forms.
    Applies header if specified or original header if not.
    """
    if not header:
        header = response_table[0]
    dict_list = []
    for response_row in response_table:
        dict_list.append(dict(zip(header, response_row)))
    return dict_list

def load_json_to_dict(relative_path:str):
    """
    Returns a dict generated from a JSON file.
    """
    try:
        with open(os.path.join(get_project_root(), relative_path), 'r', encoding='utf-8') as file:
            loaded_dict = json.load(file)            
        return loaded_dict
    except Exception:
        raise ModuleException(f"unexpected error while loading {relative_path} to dict")

def export_dict_as_json(data, relative_path: str):
    """
    Saves a dict as JSON to specified path relative to project root.
    Ensures that the folder path exists.
    """
    try:
        # Get the full path by combining project root and relative path
        full_path = os.path.join(get_project_root(), relative_path)

        # Ensure the directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Write the dictionary to the JSON file
        with open(full_path, 'w') as json_file:
            json.dump(data, json_file, indent=4)

    except:
        raise ModuleException(f"couldn't export dict to {relative_path}")

def jsonify_array(data):
    """
    Converts lists that have numeric-like keys back into dictionaries and removes any None values.
    Can be used to re-correct a dictionary that was transformed by Firebase.
    
    :param data: The dictionary to fix.
    :return: A corrected dictionary with lists turned back into dicts.
    """
    if isinstance(data, list):
        # Convert list back to a dictionary if it's filled with dict-like entries and non-null elements
        return {str(i): jsonify_array(v) for i, v in enumerate(data) if v is not None}
    
    elif isinstance(data, dict):
        # Recursively fix any nested dicts/lists
        return {k: jsonify_array(v) for k, v in data.items()}
    
    return data  # Base case: return the data as is if it's not a list or dict

def dejsonify_array(jsonified_array:dict):
    """
    Extracts the matrix of values from a dict disregarding the keys.
    To be used where keys are simple indices with no additional meaning.
    """
    if isinstance(jsonified_array,dict):
        array = []
        for val in jsonified_array.values():
            array.append(dejsonify_array(val) if isinstance(val,dict) else val)
        return array

def compare_dicts(dict1, dict2, parent_key=''):
    """
    Compare two dictionaries and return the list of nodes where they differ,
    along with the state of the second dictionary at those nodes.
    
    :param dict1: The first dictionary (original state).
    :param dict2: The second dictionary (new state).
    :param parent_key: Used internally for recursive key tracking (do not pass anything).
    :return: A list of nodes where the two dicts differ.
    """
    try:
        differences = []

        # If the node contains just a variable
        if isinstance(dict2,dict) == False:
            return [{'':dict2}]

        # Case when dict1 is None but dict2 is not (new node added)
        if dict1 is None and dict2 is not None:
            return flatten_dict(dict2, parent_key)

        # Case when dict2 is None but dict1 is not (node deleted)
        if dict2 is None and dict1 is not None:
            return [{'':None}]

        # Case when both dicts are None
        if dict1 is None and dict2 is None:
            return []

        # Get the union of keys from both dictionaries
        all_keys = set(dict1.keys()).union(set(dict2.keys()))

        for key in all_keys:
            full_key = f"{parent_key}/{key}" if parent_key else key

            # If the key is in only one of the dictionaries
            if key not in dict1:
                differences.append({full_key: dict2[key]})
            elif key not in dict2:
                differences.append({full_key: None})
            else:
                # If both values are dictionaries, compare them recursively
                if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                    differences.extend(compare_dicts(dict1[key], dict2[key], full_key))
                # If the values differ, add to the differences
                elif dict1[key] != dict2[key]:
                    differences.append({full_key: dict2[key]})

        return differences
    except:
        raise ModuleException(f"couldn't compare dicts")

def flatten_dict(d, parent_key=''):
    """
    Flatten a nested dictionary into a list of key-value pairs.
    
    :param d: The dictionary to flatten.
    :param parent_key: Used internally for recursive key tracking (do not pass anything).
    :return: A flattened dictionary with terminal addresses as keys.
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}/{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key))
        else:
            items.append({new_key: v})
    return items

def update_nested_dict(dict_to_update: dict, key_path: str, value):
    """
    Updates a nested dictionary using a key path string.

    Parameters:
    - dict_to_update: The dictionary to update
    - key_path: A string representing the path in the nested dictionary (e.g., 'key1/key2/')
    - value: The value to set at the final key
    """
    keys = key_path.strip('/').split('/')
    for key in keys[:-1]:
        dict_to_update = dict_to_update.setdefault(key, {})
    dict_to_update[keys[-1]] = value

def read_nested_dict(dict_to_read: dict, key_path: str):
    """
    Reads a value from a nested dictionary using a key path string.

    Parameters:
    - dict_to_read: The dictionary to read from
    - key_path: A string representing the path in the nested dictionary (e.g., 'key1/key2/')
    
    Returns:
    - The value found at the specified key path, or None if the path does not exist
    """
    keys = key_path.strip('/').split('/')
    for key in keys:
        dict_to_read = dict_to_read.get(key)
        if dict_to_read is None:
            return None
    return dict_to_read

#endregion

#region CSV and arrays
def find_val_in_array(nested_list, value):
    """
    Returns the positions of a value in a nested array.
    """
    positions = []
    
    def find_in_sublist(sublist, path):
        if isinstance(sublist, list):
            for index, item in enumerate(sublist):
                find_in_sublist(item, path + [index])
        elif sublist == value:
            positions.append(path)

    find_in_sublist(nested_list, [])
    return positions

def download_google_sheet_to_2D_array(spreadsheet_id, sheet = None):
    """
    Uses the Google Sheets API to download the contents of either the first sheet of a spreadsheet (if sheet == None), or from the sheet specified.
    """
    try:
        credentials = Credentials.from_service_account_file(
            os.path.join(get_project_root(),'config','secrets_and_env','sheets-access-key.json'), 
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
        service = build('sheets', 'v4', credentials=credentials)
        spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    except:
        raise ModuleException("failed to set up Google Sheets API")
    
    try:
        if sheet:
            sheet_names = []
            for sheet_data in spreadsheet_metadata['sheets']:
                sheet_names.append(sheet_data['properties']['title'])
            if sheet not in sheet_names:
                raise ModuleException(f"requested sheet '{sheet}' not in spreadsheet '{spreadsheet_metadata['properties']['title']}'")
        else:
            sheet = spreadsheet_metadata['sheets'][0]['properties']['title']
        
        range_to_get = sheet +'!A1:Z10000'

        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_to_get).execute()
        values = result.get('values', [])

        return values
    except ModuleException as e:
        raise
    except:
        raise ModuleException(f"failed to download sheet '{sheet}' from spreadsheet '{spreadsheet_metadata['properties']['title']}'")

def download_csv_to_2D_array(url:str):
    """
    Download a csv file into an unformatted raw table (2D array).
    Do not call on published versions of Google Sheets if time-critical because those won't get republished instantly upon change.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        table = []
        for line in response.content.decode('utf-8-sig').splitlines():
            table.append(line.rsplit(','))
        return table
    except:
        raise ModuleException(f"couldn't download csv from {url}")
    
def load_csv_to_2D_array(relative_path:str):
    """
    Load a csv file into an unformatted raw table (2D array) from a project path.
    """
    try:
        table = []
        with open(os.path.join(get_project_root(), relative_path), 'r', encoding='utf-8') as file:
            for line in csv.reader(file):
                table.append(line)
        return table
    except:
        raise ModuleException(f"couldn't load csv from {relative_path}")

def select_subtable_from_table(table, row_selection = None, col_selection = None):
    """
    Selects and returns a rectangular subtable from a passed 2D table.
    """
    try:
        dims = [len(table),len(table[0])]
        if row_selection is None:
            row_selection = [0, dims[0]]
        else:
            row_selection = [
                row_selection[0],
                dims[0] + row_selection[1]
            ]
        if col_selection is None:
            col_selection = [0, dims[1]]
        else:
            col_selection = [
                col_selection[0],
                dims[1] + col_selection[1]
            ]
        subtable = [row[col_selection[0]:col_selection[1]] for row in table[row_selection[0]:row_selection[1]]]
        return subtable
    except:
        raise ModuleException(f"couldn't select subtable")

def transpose_2D_array(array):
    """
    Transpose a 2D array then return it.
    """
    return [list(row) for row in zip(*array)]

def extend_2D_array(array, prepend_rows=None, append_rows=None, row_shift=0, row_spacer='', prepend_cols=None, append_cols=None, col_shift=0, col_spacer=''):
    """
    Extends an array with headers, footers in any direction etc.
    """
    if prepend_rows:
        for i, row in enumerate(prepend_rows):
            prepend_rows[i] = [row_spacer] * row_shift + row + [row_spacer] * (len(array[0]) - len(row) - row_shift)
    
    if append_rows:
        for i, row in enumerate(append_rows):
            append_rows[i] = [row_spacer] * row_shift + row + [row_spacer] * (len(array[0]) - len(row) - row_shift)

    if prepend_rows:
        array = prepend_rows + array
    if append_rows:
        array = array + append_rows

    col_shift += len(prepend_cols)
    
    if prepend_cols:
        for i, col in enumerate(prepend_cols):
            prepend_cols[i] = [col_spacer] * col_shift + col + [col_spacer] * (len(array) - len(col) - col_shift)
    
    if append_cols:
        for i, col in enumerate(append_cols):
            append_cols[i] = [col_spacer] * col_shift + col + [col_spacer] * (len(array) - len(col) - col_shift)

    array = transpose_2D_array(array)
    
    if prepend_cols:
        array = prepend_cols + array
    if append_cols:
        array = array + append_cols

    array = transpose_2D_array(array)
    
    return array

def export_2D_array_to_csv(array: list, relative_path: str):
    """
    Saves an arbitrarily extended CSV to a project path.
    Ensures that the folder path exists.
    """
    try:
        # Get the full path by combining project root and relative path
        full_path = os.path.join(get_project_root(), relative_path)

        # Ensure the directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        # Write the 2D array to the CSV file
        with open(full_path, 'w', newline='', encoding='utf-8') as csvfile:
            csv.writer(csvfile).writerows(array)
    except Exception as e:
        raise ModuleException(f"couldn't export 2D array to CSV at {relative_path}")
#endregion
#endregion

#endregion