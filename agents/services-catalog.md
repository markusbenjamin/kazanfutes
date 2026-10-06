# Service catalog

This catalog is based on the source of executable scripts in `services/`. It supports monitoring decisions without inferring behaviour from names. Update an entry when the script changes.

## How to use this catalog

- **Lifecycle** means what the script itself does. A service can be timer-backed, continuous, or manual; check `services/services_and_timers.list` and installed unit files for the actual launcher.
- **Outputs** are explicit logs, exported files, or remote writes in the source. They are candidates for monitoring.
- A missing event in an event-driven log is not automatically a service failure.
- This catalog deliberately does not assign `critical` or `revision`; those are operational decisions.

## Managed production scripts

### `aqara_and_nous_logger.py`
Reads deCONZ REST sensors, selects configured Nous and Aqara models, normalises reported values, and writes temperature, humidity, CO2, presence, and lux states to `data/logs/aqara_and_nous/aqara_and_nous.json`. Writes an execution `success` record.

### `data_and_config_uploader.py`
Syncs `data/`, `config/`, and `system/state.json` with the online repository through `sync_paths_with_repo()`. Writes execution `success` and exits non-zero if the sync fails. It has no separate delivery-receipt artifact.

### `data_formatter.py`
Locks the project data directory and derives daily chart-oriented data from raw logs, including room measurements, set temperatures, overrides, KPIs, external temperature, gas consumption, heating state, valve states, and pump power. Writes one execution result per formatting action; it does not acquire device data.

### `device_watchdog.py`
Runs the physical-infrastructure watchdog once. It observes deCONZ, Tuya pumps, heatmeters, Shellys, HomeWizard, and selected log-backed infrastructure; persists state and incidents; and may notify about physical-infrastructure issues. See `docs/device_watchdog.md`. It is separate from service/data monitoring.

### `electric_meter_logger.py`
Reads one HomeWizard P1 HTTP sample and appends instantaneous power, cumulative import/export counters, voltage, current, and tariff to `data/logs/electricity/main_meter.json`. Writes execution `success`.

### `electric_submeters_logger.py`
Continuous Shelly push-event listener, with one thread per configured submeter device. Appends received events to `data/logs/electricity/submeters.json`. It writes `success: true` only after listener startup, not periodically. No event can be normal.

### `error_manager.py`
Processes the application error registry and buffer: re-registers buffered errors, writes errors and daily reports by severity, emails severity-3 errors, sends daily reports, and archives checked errors. It does not inspect systemd state or data freshness.

### `external_temp_scraper_and_logger.py`
Scrapes external temperature, writes it to Firebase `system/state/external_temp`, and appends it to `data/logs/external_temp/external_temp.json`. Writes execution `success`.

### `gasmeter_logger.py`
Continuous GPIO listener for the gas-meter relay. Appends a log record only when the pin state changes, at `data/logs/gas_consumption/gas_relay_turns.json`. On a completed 1-to-0 dial transition, writes elapsed turn time to Firebase `system/state/gas/dial_turn_secs`. It has no periodic heartbeat; no event can be normal.

### `heating_control.py`
Runs one heating-control cycle: loads room/cycle metadata, heating configuration, and condensed schedule; reads the heating switch; acquires system state; compares and executes commands; and exports state to Firebase and `system/state.json`. Writes separate success fields for initialization, acquisition, command stages, and final export. Guarded failures are written to Firebase `system/control/error`.

### `heatmeters_logger.py`
Reads selected fields from heatmeters 1-4, writes a lean state to Firebase `system/state/heatmeters`, writes full readings to `data/logs/heat_delivery/heatmeters_state.json`, and writes execution `success`.

### `light_state_manager.py`
Reads configured lights, calculates a target state from the current hour and per-light overrides, and writes changed light states. Its execution log contains successful and failed light names. It has no separate state-data log.

### `occupancy_logger.py`
Calls `get_rooms_occupancy()` and appends room occupancy state to `data/logs/occupancy/occupancy.json`. Writes execution `success`.

### `open_close_logger.py`
Continuous deCONZ poller for sensors with an `open` state. At startup it records every observed contact state; afterwards it records new sensors and open/closed transitions to `data/logs/open_close/open_close_events.json`. It has no periodic heartbeat; no contact event can be normal.

### `presence_logger.py`
Calls `get_presence_rooms()` and appends room presence state to `data/logs/presence/presence_all.json`. Writes execution `success`.

### `presence_pattern_calculator.py`
Reads the previous 28 days of rotated presence logs, derives room/day/hour occupancy frequencies at five-minute resolution, and exports `config/scheduling/local_scheduling_files/occupancy.json`. It does not write a service-execution record.

### `pump_power_logger.py`
Continuous pump-power poller for pumps 1-4. Writes an execution `success` record each cycle, but writes pump-power data to `data/logs/pumps/power.json` and Firebase `system/state/pumps` only when a reading changes. Its delay is two or ten seconds. A stale power-data file alone is not a reliable failure signal.

### `parasoll_battery_logger.py`
Every five minutes, reads deCONZ and appends one battery-health snapshot for every IKEA PARASOLL sensor to `data/logs/zigbee/parasoll_batteries.json`. Each physical sensor entry preserves its raw reported battery value, low-battery flag, reachability, last-seen time, and Zigbee identity; it does not infer an ambiguous raw battery scale.

### `pv_logger.py`
Uses headless Chromium/Selenium to obtain one FusionSolar live inverter row and appends it to `data/logs/electricity/pv_inverter.json`. Writes execution `success`.

### `radiator_temps_logger.py`
Discovers configured Shelly radiator devices, reads peripheral temperatures, and appends a reduced device/peripheral map to `data/logs/radiator_temps/radiator_temps.json`. Resolution errors for required devices cause a failed execution result.

### `schedule_and_config_updater.py`
Polls Firebase update state, refreshes local heating configuration and scheduling files, generates the heating switch and a seven-day condensed schedule, exports the schedule locally and to Firebase, and updates valid requests. It sleeps ten seconds between loops and exits after roughly 30 minutes. It writes per-action execution records. It updates configuration and scheduling artifacts; it is not the thermostat-management script.

### `temperature_and_humidity_logger.py`
Calls `get_room_temps_and_humidity(just_controlled=False)` and appends the result to `data/logs/temperature_and_humidity/temperature_and_humidity.json`. Writes execution `success`.

### `thermostats_manager.py`
Reads each thermostat's name, valve, heatsetpoint, temperature, external sensor temperature, battery, last-seen, and last-updated fields; writes them to `data/logs/thermostats/thermostats_state.json`; and registers a severity-3 error for batteries below 20%. It calibrates all thermostats only when it runs on Monday at 04:00 or 04:01. It does **not** calculate or change thermostat setpoints, and does **not** command valve position in its normal run.

### `weather_station_logger.py`
Discovers the configured Shelly gateway, reads the configured WS90 weather station through it, and appends its state to `data/logs/weather_station/weather_station.json`. Writes execution `success`.


### service_data_watchdog.py

Runs the unified service/data watchdog. It discovers every unit in
services/services_and_timers.list, checks timer state, continuous-service state, and
the last result of timer-backed jobs, and evaluates declared periodic data
streams against the interval derived from their systemd timers plus a global
grace. Event-driven streams are service-monitored without a stale-data rule.
New units and unclassified log streams create a bundled review notification.
It persists active, solved, and retired incidents separately from the physical
watchdog. It does not restart units.

## Legacy and manual scripts

### `heating_control_old.py`
Older heating-control implementation. Its source follows the broad sequence of acquiring switch and system state, comparing and commanding, executing commands, and exporting state. It is not listed in `services_and_timers.list`.

### `turn_heating_off.py`
Manual heating-off utility. Calls `shutdown_heating(calibrate_thermostats=True)`, then writes heating-off state, pump state, boiler state, and observed valve states to Firebase and `system/state.json`. It is not listed in `services_and_timers.list`.

### `services_system_and_utils_syncer.py`
Attempts to sync `services/`, `system/`, and `utils/` with the online repository. It sets project logging off, so its final `log({"success": ...})` is printed rather than written through the normal execution-log path. It is not listed in `services_and_timers.list`.

## Service coordinator

### `service_manager.sh`
Linux coordinator for the managed units. It builds `kazanfutes.target` wants from `services_and_timers.list`, starts/stops units, validates and reports unit state, and installs/runs a recovery timer. Recovery starts inactive timers and continuous services, but intentionally does not start timer-backed services between firings. It can send delayed outage and recovery email for expected-active units. It does not decide whether a timer-backed job produced valid data or whether a data stream is fresh.
