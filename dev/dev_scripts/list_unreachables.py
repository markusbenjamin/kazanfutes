from utils.project import *
import pprint

PRINT = True
SEND = False

try:
    unreachable_devices = get_unreachable_zigbee_devices()
    if PRINT:
        pprint.pprint(unreachable_devices, sort_dicts=False)
    if SEND:
        send_email(
            to=settings["admin_email"],
            subject="Unreachable ZigBee devices",
            body=pprint.pformat(unreachable_devices, sort_dicts=False)
        )

except Exception:
    raise ServiceException("couldn't send unreachable ZigBee device report", severity=2)