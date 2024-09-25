"""
The only continuously running script. If fails, gets restarted by corresponding service file.

Listens to Firebase and refreshes heating control config, schedules and overrides.
Generates condensed schedule (weekly schedule + overrides) based on latest info got.
If successful, uploads condensed schedule to Firebase.

Usual logging and reporting.
"""

from utils.project import *

import firebase_admin
from firebase_admin import credentials as firebase_credentials
from firebase_admin import db as firebase_db

def initialize_firebase():
    """
    Establishes connection to Firebase in current scope.
    """
    firebase_admin.initialize_app(
        firebase_credentials.Certificate(os.path.join(get_project_root(),'secrets_and_env','kazanfutes_firebase_key.json')), 
        {'databaseURL': settings.get('firebase_url')}
    )

def firebase_update_data_getter(event):
    """
    Returns the contents of a detected Firebase update.
    """
    report(f'Firebase update at path: {event.path}, data: {event.data}')
    return event.data

def create_firebase_listener(path:str='',callback = firebase_update_data_getter):
    """
    Returns an active Firebase listener at specified path.
    
    The listener will run the callback function with a passed 'event' object that has:
        - event.path
        - event.data.

    The default callback function simply reports the update and returns the data.
    """
    return firebase_db.reference(path+'/').listen(callback)

def send_to_firebase(path:str, data:dict, trials = 0):
    try:
        ref = firebase_db.reference(path)
        ref.update(data)
    except Exception as e:
        if trials < 10:
            report(f"Couldn't send to firebase due to {e}, trying again in 1 s for the {trials}-th time.")
            time.sleep(1)
            send_to_firebase(path, data, trials = trials+1)
        else:
            report(f"Couldn't send to firebase due to {e} 10 times, not trying again.")

def my_custom_firebase_callback(event):
    report(f'Custom callback: update at path: {event.path}, data: {event.data}')

initialize_firebase()
firebase_listener = create_firebase_listener('test')
send_to_firebase('test', {'bla':'bla'}, 1)