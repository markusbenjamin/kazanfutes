"""Wrapper functions for everything IO."""

from utils.base import *
import utils.deconz as deconz

def get_room_temps_and_humidity():
    """
    Returns dated temperature and humidity readings for all rooms in config.
    """

    try:
        from datetime import datetime
        
        sensors_state = deconz.read_sensors()

        sensor_temps_and_hums = {}
        for sensor_id, sensor in sensors_state:
            if sensor.type == "ZHATemperature":
                last_updated = datetime.strptime((sensor.raw)['state']['lastupdated'], "%Y-%m-%dT%H:%M:%S.%f").strftime("%Y-%m-%d-%H-%M")
                if sensor.name not in sensor_temps_and_hums:
                    sensor_temps_and_hums[sensor.name] = {'temp':'none','hum':'none','last_updated':'none'}
                sensor_temps_and_hums[sensor.name]['temp'] = sensor.temperature
                sensor_temps_and_hums[sensor.name]['last_updated'] = last_updated
            elif sensor.type == "ZHAHumidity":
                last_updated = datetime.strptime((sensor.raw)['state']['lastupdated'], "%Y-%m-%dT%H:%M:%S.%f").strftime("%Y-%m-%d-%H-%M")
                if sensor.name not in sensor_temps_and_hums:
                    sensor_temps_and_hums[sensor.name] = {'temp':'none','hum':'none','last_updated':'none'}
                sensor_temps_and_hums[sensor.name]['hum'] = sensor.humidity
                sensor_temps_and_hums[sensor.name]['last_updated'] = last_updated

        rooms_info = project.get_rooms_info()

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
        errors.DeconzError,
        errors.ProjectError
     ) as e:
        raise errors.ProjectIOError(f"Couldn't read sensor state due to: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e
    except Exception as e:
        raise errors.ProjectIOError(f"Unexpected error while reading sensor state: {e}", original_exception=e, include_traceback=settings.get_detailed_error_reporting()) from e