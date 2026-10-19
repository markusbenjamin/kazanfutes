"""
Scrapes and logs legacy web temperature; does not publish dashboard values.
"""

from utils.project import *

success = False
try:
    external_temp = scrape_external_temperature()
    # Firebase external_temp belongs exclusively to weather_station_logger (WS90).
    log_data({"external_temp":external_temp},'external_temp/external_temp.json')
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to scrape and log external temperature", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to scrape and log external temperature", severity = 2)

log({"success":success})
