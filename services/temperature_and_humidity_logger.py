"""
Logs temperature and humidity values from the rooms as specified in rooms.json.
"""

from utils.project import *

init_logger(log_file=f'{get_project_root()}/data/logs/temperature_and_humidity/temperature_and_humidity.json')

room_temps_and_humidity = get_room_temps_and_humidity()

log_data(room_temps_and_humidity)