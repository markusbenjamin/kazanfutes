import utils.project as project
import utils.io as io
import logging
from logging.handlers import TimedRotatingFileHandler
import json

project_root = project.get_project_root()

log_file_path = f'{project_root}/data/logs/temperature_and_humidity/temperature_and_humidity.json'
handler = TimedRotatingFileHandler(log_file_path, when='midnight', interval=1)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

room_temps_and_humidity = io.get_room_temps_and_humidity()

logging.info(json.dumps(room_temps_and_humidity))