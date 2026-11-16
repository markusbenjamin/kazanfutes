# Shelly plug rain control

`shelly_plug_manager.service` is part of the existing kazanfutes service manager.
It checks once a minute and controls switch 0 on the two boiler plugs by the
stable MAC identities in `config/shelly_devices.json`. Plug 2 is optional until
first reached; its first appearance automatically joins normal control.

- OFF when WS90 precipitation increased by **more than 10 mm in the preceding
  30 minutes**. Exactly 10 does not initiate a shutdown.
- After a rain shutdown, remain OFF until the trailing amount is **less than
  5 mm continuously for 60 minutes**. Exactly 5 resets the timer.
- Restart, clock changes, monitoring gaps and weather-source changes reset the
  recovery timer. The rain latch survives restarts and is saved before commands.
- If WS90 is stale, has a counter reset, or lacks a complete history, use
  Open-Meteo. It uses the site's existing PV-model coordinates (47.4879, 19.0929),
  configurable in `services/shelly_plug_manager.json`. The latest two completed
  15-minute model precipitation intervals are summed: no future or centred bin.
  This estimate can lag the present by up to 15 minutes and is less local than
  WS90. WS90 values retain the gateway's reported millimetre scale.
- If both sources fail, email once per outage and retry failed email delivery.
  Hold actual relay states, inhibit turn-on, and require a fresh dry hour before
  restoration. An existing rain shutdown remains latched.
- With normal weather permission, restore unexpected OFF states. Change a relay
  only when necessary and confirm every command by reading its output state.
- Electrical/temperature errors latch a per-plug protection block. They are never
  automatically cleared or repeatedly overridden. After physical inspection,
  stop the manager, run `python services/shelly_plug_manager.py
  --clear-protection boiler_1_plug` (or plug 2), then start it again.

Runtime state is `/var/lib/kazanfutes-rain-plugs/state.json`, separate from Git
and project data logs. `python services/shelly_plug_manager.py --show-state`
prints it. `--dry-run` previews one check without relay commands, controller
state writes or emails; device discovery may refresh its existing shared cache.
The watchdog suppresses expected OFF only while controller intent is fresh and
the MAC matches. Connectivity and active protection faults remain monitored.

Firebase status is published each cycle at **`system/state/rain_protection`**.
It includes mode, running flag, timestamp/freshness allowance, rainfall amount,
source/window, recovery countdown, thresholds, plug states and active issues.
A PATCH replaces only this child and preserves the rest of heating state.
Publication happens after relay control, with a three-second timeout; failures
are recorded locally and retried next cycle. Graceful stop publishes `stopped`.
Consumers must check freshness as a crashed process cannot publish its own stop.

Validation: `python -m unittest services.test_shelly_plug_manager`.

## Boiler inhibition and residual circulation

`heating_interlock` in `services/shelly_plug_manager.json` enables coordination
with the existing heating controller. Rain protection owns the Shelly plugs;
the heating controller remains the sole normal writer of boiler GPIO and pumps.
The master heating OFF switch still stops the whole system, including TRVs.

During a rain shutdown, boiler enable is forced OFF. Each circuit keeps its
normal room heat requests, but its pump is permitted only with a fresh supply
temperature **strictly above 40 C**. At 40 C or below, no heat request, or missing
water data, that pump stops. Existing heat-meter mapping comes from
`config/heating_monitor.json`; no boiler/circuit associations are inferred.
Water snapshots are read locally from the existing heat-meter logger, without
extra Modbus polling. Maximum observation age is 180 seconds.

Running, eligible pumps continue immediately. Starting requires two different
fresh warm observations; a stopped pump waits at least five minutes before
restarting. The controller alone persists these timers in `heating_status.json`.
Unserved demand cannot increase PID integral bias; normal gains are unchanged.

After the existing dry-hour condition, restoration waits for a fresh, matching
controller acknowledgement that boiler GPIO is OFF. The manager restores and
reads back plug outputs while boiler enable stays inhibited, then grants normal
heat generation. Optional plug 2 does not block restoration before first seen.
Partial restoration holds already-powered plugs instead of cycling them. New
rain cancels the acknowledgement and takes immediate mains-OFF priority.

Permissions and boiler GPIO operations share `heat_permission.lock`. A new rain
restriction is saved atomically without waiting on that lock, so a stuck GPIO
operation cannot delay mains OFF. Permission grants always require the lock and
verified acknowledgement/readbacks. Commands carry the rain-episode generation;
old queued boiler-ON commands cannot revive after restoration. Missing/stale
policy blocks boiler enable. Weather-source failure alone retains the agreed
hold policy and does not invent a new rain event.

Firebase `system/state/rain_protection` additionally contains `heating_interlock`
and the latest `heating_controller` status, including per-circuit requests,
temperatures, pump commands and blocking reasons. Cold-water diagnostics are
suppressed for intentional shutdown and a ten-minute post-restoration warmup;
pump, flow, meter-data and electrical protection checks remain active.

For a local, read-only current-versus-rain decision comparison on the Pi:
`python services/shelly_plug_manager.py --preview-heating`. It issues no commands,
writes no controller state, and sends no email. New interlock tests:
`python -m unittest services.test_heating_rain_interlock`.
