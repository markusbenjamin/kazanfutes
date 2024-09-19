"""
Tasks:
    Load and setup:
        Load rooms config.
        Download and refresh local copy of run config.
        Load local copy of run config.
        Download and refresh local copy of weekly schedule.
        Load local copy of weekly schedule.
        Download and refresh local copy of overrides (both room and cycle).
        Load local copy of overrides.

    Compare and issue commands:
        Load set temps.
        Measure actual temps.
        Compare set to actual by room, add up votes per cycle.
        Get boiler and pump states.
        Compare unitized votes to states.
        Issue commands.

    Execute commands:
        Load issued commands.
        Go over commands and execute unexecuted past ones.
        Mark and filter successfully executed commands.

Integrated throughout:
    Verbose reporting.
    Runtime success logging of main tasks.
    Feature logging of system state and decisions.
    Error registration.
    Firebase reporting according to dashboard needs.
"""

from utils.project import *

try:
    success = True
    try:
        rooms = get_rooms_info()
        cycles = get_cycles_info()
    except Exception as e:
        success = False
        raise HeatingConfigError(f"Couldn't load system config due to {e}",original_exception=e,severity=0)
    try:
        pass
    except Exception as e:
        success = False
        raise HeatingConfigError(f"Couldn't load run config due to {e}",original_exception=e,severity=0)
finally:
    log({"success_load_config":success})