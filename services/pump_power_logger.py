"""
Logs pump power.
- always logs when any pump reading differs from previous
- drops polling interval to FAST if any difference exceeds THRESH
"""

from utils.project import *          # timestamp(), get_pump_powers(), log_data(), log(), report()

system_node = JSONNodeAtURL(node_relative_path='system')

settings["verbosity"] = True

PUMPS   = ['1', '2', '3', '4']
FAST    = 2        # s   for transients
SLOW    = 10       # s   for steady state
THRESH  = 0.5      # W   <large> change
EPS     = 0.01     # W   minimal change to log

last = None

while True:
    success = False
    try:
        curr = get_pump_powers(PUMPS)                    # {'1': xx.x, ...}
        if last is None:
            diff_any  = True
            diff_big  = True
        else:
            diffs     = [abs(curr[p] - last[p]) for p in PUMPS]
            diff_any  = any(d > EPS     for d in diffs)  # log on any change
            diff_big  = any(d > THRESH for d in diffs)  # decide pace

        if diff_any:
            log_data({"timestamp": timestamp(), "power": curr},'pumps/power.json')
            system_node.write({"power":curr,"last_updated":timestamp()},'state/pumps')
            report(f"Pump powers logged: {curr}, sleep {FAST if diff_big else SLOW} secs.", verbose=True)
        else:
            report(f"Pump powers: {curr}, sleep {FAST if diff_big else SLOW} secs.", verbose=True)            

        success = True
        last = curr
    except ModuleException as e:
        ServiceException("module error acquiring pump powers", original_exception=e, severity=2)
    except Exception:
        ServiceException("module error acquiring pump powers", severity=2)

    log({"success": success})
    time.sleep(FAST if diff_big else SLOW)
