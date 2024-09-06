"""
Logs temperature and humidity values from the rooms as specified in rooms.json.
"""

from utils.project import *
import logging
from logging.handlers import TimedRotatingFileHandler
import json

log_file_path = f'{get_project_root()}/data/logs/temperature_and_humidity/temperature_and_humidity.json'
handler = TimedRotatingFileHandler(log_file_path, when='midnight', interval=1)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

room_temps_and_humidity = get_room_temps_and_humidity()

logging.info(json.dumps(room_temps_and_humidity))