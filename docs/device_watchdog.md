# Physical-infrastructure watchdog

`services/device_watchdog.py` observes physical infrastructure without changing
any device state. It is independent from `error_manager.py` and does not
monitor boiler GPIO state.

The configuration's `mode` controls notification behaviour. `shadow` writes
current, active, and solved state but sends no email and no Healthchecks ping;
`live` additionally sends the approved alerts and heartbeat.

## Before enabling live notifications

1. Run shadow mode on the Raspberry Pi:

   ```bash
   python3 services/device_watchdog.py --table
   ```

   To inspect the saved active table without querying devices:

   ```bash
   python3 services/device_watchdog.py --show-state
   ```

   The table includes a `TYPE` column: Zigbee entries show their reported
   maker/model when available; other infrastructure has a concise equipment
   descriptor such as `Tuya smart plug` or `DS18B20 via Shelly`.

   Detailed per-condition output is the default and can be requested
   explicitly with `--detailed`. To group all conditions under one device:

   ```bash
   python3 services/device_watchdog.py --show-state --grouped
   ```

   The `--grouped` and `--detailed` choices also apply to `--table`,
   `--dry-run`, and `--show-solved`. Email reports always use grouped output.

   A Parasoll temporarily fitted with a non-rechargeable battery can be kept
   in the maintenance inventory by its configured name:

   ```bash
   python3 services/device_watchdog.py --set-parasoll-temporary-battery "kisudvar_ajto"
   python3 services/device_watchdog.py --list-parasoll-temporary-batteries
   python3 services/device_watchdog.py --clear-parasoll-temporary-battery "kisudvar_ajto"
   ```

   Names are matched case-insensitively against the known Parasoll inventory
   and stored under the canonical configured name. Set and clear operations
   refresh watchdog state immediately. The marker is always revision-class,
   appears in daily reports until cleared, and then enters solved history.

   The solved-history table is also available locally:

   ```bash
   python3 services/device_watchdog.py --show-solved
   ```

2. Review the generated inventory. No manual battery-scale calibration is
   required. The watchdog preserves `battery_raw`, `battery_scale`, and
   `battery_percent` for every applicable device. A value above 100 confirms
   the 0..200 half-percent convention automatically. Values at or below 100
   are intrinsically ambiguous, so after seven days and twelve observations
   the watchdog uses a conservative half-percent conversion. This can alert
   early for a genuine 0..100 device, but cannot mistake a low 0..200 reading
   for a safe value. The state includes scale confidence and learning evidence.
   deCONZ also uses zero as an uninitialized/default battery value. A raw zero
   accompanied by `lowbattery: false` is therefore retained for diagnosis but
   is not normalized or alerted on. An explicit low-battery flag, stale data,
   or loss of reachability still opens an incident independently.

3. Confirm the critical device profiles. `critical_pump`,
   `critical_danfoss_valve`, and their `critical_dependency` are critical only
   while `config/heating_switch.json` has `"system": 1`; otherwise their
   incidents are revision-class. Parasoll is revision-class except that a low
   battery is immediate.

4. Review the initial thresholds in `config/device_watchdog.json`:

   - Parasoll immediate low-battery alert: 40% normalized.
   - Parasoll revision visibility: 50% normalized.
   - Gas-meter no-pulse condition: 36 hours.
   - Battery learning window: 7 days and 12 observations.
   - Heating context: `config/heating_switch.json` must report `"system": 1`
     for heating-device incidents to be critical.

5. Once a Healthchecks.io check exists, create this untracked secret file on
   the Pi containing only its supplied ping URL:

   ```text
   config/secrets_and_env/healthchecks_device_watchdog_url
   ```

   The service pings it only after a complete live run persists local watchdog
   state. A missing secret disables the optional external heartbeat; it does
   not make the watchdog fail.

6. Install/copy the `device_watchdog.service` and `device_watchdog.timer`
   systemd units, then add them through the existing service manager. The timer
   runs every five minutes.

## Outputs

- `system/device_watchdog_state.json`: current observable device table.
- `system/device_watchdog_incidents.json`: currently active incidents and
  restart-safe pending counters.
- `system/device_inventory.json`: forward-only MAC/IEEE inventory. It retains
  every device observed from now on, current manufacturer/model/endpoints,
  name history, structural changes, disappearance/reappearance, and watchdog
  incident lifecycles. Existing devices seed the file on its first run; older
  history is not reconstructed.
- `system/device_watchdog_manual_state.json`: manually managed Parasoll
  temporary-battery markers.
- `data/logs/device_watchdog/solved_incidents.jsonl`: automatically resolved
  incident history.
- `data/logs/device_watchdog/digest.jsonl`: digest audit trail.

The scheduled email is a change bulletin, not the complete to-do list. It is
sent only when an incident has been added or resolved since the last successful
email. It contains only those changes, grouped first under `ADDED INCIDENTS`
and `RESOLVED INCIDENTS`, then by device within each section. The complete
current list remains available through the CLI `--show-state` views.

The configured daily comparison runs at 08:00 local time. Changing ages,
measurements, severity, and other evidence do not create repeated emails for
the same incident. Solving the final incident sends a resolved-incidents email;
an initially empty installation remains quiet.

## Interpretation rules

- deCONZ `/devices` entries which are not the coordinator and expose no
  `/sensors` or `/lights` resources are reported as revision-class
  `incomplete_interview` incidents after two consecutive runs. Known IEEE
  addresses can receive a friendly report name through
  `deconz.incomplete_device_names` in `config/device_watchdog.json`.
- Presence: no movement is normal; unreachable or stale `lastseen` is not.
- Gas meter: no pulse for 36 hours is a revision incident, while its continuous
  logger's systemd state is an independent observation.
- Submeter pulses have no generic event-age threshold because some circuits may
  legitimately have no daily load; Shelly availability is still monitored.
- The watchdog does not infer boiler state from the GPIO shadow file.
- Heating-dependent severity uses the configured system master switch, not a
  boiler command or a claim about physical boiler operation. A missing switch
  safely results in revision severity.
