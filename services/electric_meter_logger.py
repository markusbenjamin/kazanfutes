"""
Reads and logs one HomeWizard P1 smart meter sample.
"""

from utils.project import *

P1_METER_URL = "http://192.168.29.88/api/v1/data"

system_node = JSONNodeAtURL(node_relative_path='system')

def read_meter():
    response = requests.get(P1_METER_URL, timeout=5)
    response.raise_for_status()
    return response.json()


def make_log_record(data):
    return {
        "timestamp": timestamp(),

        # instantaneous net power
        # positive = importing from grid
        # negative = exporting to grid
        "active_power_w": data.get("active_power_w"),

        # cumulative import counters, kWh
        "total_power_import_kwh": data.get("total_power_import_kwh"),
        "total_power_import_t1_kwh": data.get("total_power_import_t1_kwh"),
        "total_power_import_t2_kwh": data.get("total_power_import_t2_kwh"),
        "total_power_import_t3_kwh": data.get("total_power_import_t3_kwh"),
        "total_power_import_t4_kwh": data.get("total_power_import_t4_kwh"),

        # cumulative export counters, kWh
        "total_power_export_kwh": data.get("total_power_export_kwh"),
        "total_power_export_t1_kwh": data.get("total_power_export_t1_kwh"),
        "total_power_export_t2_kwh": data.get("total_power_export_t2_kwh"),
        "total_power_export_t3_kwh": data.get("total_power_export_t3_kwh"),
        "total_power_export_t4_kwh": data.get("total_power_export_t4_kwh"),

        # useful electrical context
        "active_voltage_l1_v": data.get("active_voltage_l1_v"),
        "active_voltage_l2_v": data.get("active_voltage_l2_v"),
        "active_voltage_l3_v": data.get("active_voltage_l3_v"),

        "active_current_l1_a": data.get("active_current_l1_a"),
        "active_current_l2_a": data.get("active_current_l2_a"),
        "active_current_l3_a": data.get("active_current_l3_a"),

        # current tariff register
        "active_tariff": data.get("active_tariff"),
    }

success = False
try:
    data = read_meter()
    out = make_log_record(data)

    #system_node.write({"last_reading": out}, "state/electricity/...")
    log_data(out, "electricity/main_meter.json")
    report(json.dumps(out, ensure_ascii=False))
    success = True
except ModuleException as e:
    ServiceException(
        "Module error while trying to read and log electric main meter data",
        original_exception=e,
        severity=2
    )

except Exception:
    ServiceException(
        "Unexpected error while trying to read and log electric main meter data",
        severity=2
    )

#Log execution
log({"success":success})