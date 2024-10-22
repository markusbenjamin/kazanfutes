"""
Scrapes and logs external temperature.
"""

from utils.project import *

success = False
try:
    external_temp = scrape_external_temperature()
    system_node = JSONNodeAtURL(node_relative_path='system')
    system_node.write({"external_temp":external_temp},"state")
    log_data({"external_temp":external_temp},'external_temp/external_temp.json')
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to scrape and log external temperature", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to scrape and log external temperature", severity = 2)

log({"success":success})