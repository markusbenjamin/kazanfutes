"""Pure fault detection and reporting for fresh heating-monitor observations.

No device I/O or historical-log reads. Times are UTC epoch seconds; state keeps
only incident timers and a bounded history of measurements made by this monitor.
"""
from __future__ import annotations

import copy
import math
from datetime import datetime

VERSION = 1
CYCLES = ("1", "2", "3", "4")


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def fresh(reading, now, max_age):
    stamp = number(reading.get("epoch"))
    return not reading.get("error") and stamp is not None and 0 <= now - stamp <= max_age


def new_state():
    return {"version": VERSION, "last_epoch": None, "on_since": {},
            "candidates": {}, "incidents": {}, "history": [], "outbox": None}


def validate_config(config):
    if config.get("mode") not in ("shadow", "live"):
        raise ValueError("mode must be shadow or live")
    for key in ("max_sample_gap_seconds", "command_max_age_seconds", "reading_max_age_seconds",
                "pump_fault_seconds", "flow_grace_seconds", "flow_fault_seconds",
                "warmup_seconds", "thermal_fault_seconds", "missing_seconds",
                "recovery_seconds", "reminder_seconds", "retry_seconds",
                "collector_timeout_seconds", "camera_timeout_seconds", "email_timeout_seconds"):
        value = number(config.get(key))
        if value is None or value <= 0:
            raise ValueError(f"{key} must be positive and finite")
    if not isinstance(config.get("thermal_bad_checks"), int) or config["thermal_bad_checks"] < 2:
        raise ValueError("thermal_bad_checks must be an integer >= 2")
    if set(config.get("cycles", {})) != set(CYCLES):
        raise ValueError("configure all four cycles explicitly")
    meters = []
    for cycle, limits in config["cycles"].items():
        meter = limits.get("meter")
        if type(meter) is not int or meter not in range(1, 5):
            raise ValueError(f"cycle {cycle}: invalid heat meter")
        meters.append(meter)
        for key in ("min_pump_w", "min_flow_m3h", "min_supply_c", "min_heat_w",
                    "warming_rise_c"):
            value = number(limits.get(key))
            if value is None or value < 0:
                raise ValueError(f"cycle {cycle}: invalid {key}")
    if len(set(meters)) != 4:
        raise ValueError("heat meter mapping must be one-to-one")


def evaluate(previous, snapshot, config):
    """Advance timers; absent data never counts as a zero reading or recovery."""
    state = copy.deepcopy(previous) if previous.get("version") == VERSION else new_state()
    now = snapshot["epoch"]
    last = state.get("last_epoch")
    gap = last is not None and (now < last or now - last > config["max_sample_gap_seconds"])
    if gap:
        state["on_since"] = {}
        state["candidates"] = {}
        state["history"] = []
        for incident in state["incidents"].values():
            incident["healthy_since"] = None
    commands = snapshot["commands"]
    command_ok = commands.get("available") is True
    conditions = {}
    summary = {}
    def condition(key, bad, delay, label, detail, checks=1):
        conditions[key] = (bad, delay, checks, label, detail)

    condition("monitor:commands", not command_ok, config["missing_seconds"],
              "Heating command state unavailable", commands.get("error") or "Current command state readable")
    for cycle in CYCLES:
        limits = config["cycles"][cycle]
        demand = commands.get("cycles", {}).get(cycle) if command_ok else None
        if demand is True:
            state["on_since"].setdefault(cycle, now)
        else:
            state["on_since"].pop(cycle, None)
        on_seconds = now - state["on_since"].get(cycle, now)
        pump = snapshot["pumps"].get(cycle, {})
        meter = snapshot["heatmeters"].get(str(limits["meter"]), {})
        pump_w = number(pump.get("power_w"))
        pump_ok = fresh(pump, now, config["reading_max_age_seconds"]) and pump_w is not None and type(pump.get("on")) is bool
        fields = ("flow_temperature_c", "return_temperature_c", "volume_flow_m3h", "power_w")
        meter_ok = fresh(meter, now, config["reading_max_age_seconds"]) and all(number(meter.get(k)) is not None for k in fields)
        def gated(value):
            return value if demand is True else False if demand is False else None
        condition(f"{cycle}:pump_data", gated(not pump_ok), config["missing_seconds"],
                  f"Cycle {cycle}: pump measurement unavailable", pump.get("error") or "Missing, invalid or stale pump observation")
        condition(f"{cycle}:meter_data", gated(not meter_ok), config["missing_seconds"],
                  f"Cycle {cycle}: heat-meter measurement unavailable", meter.get("error") or "Missing, invalid or stale heat-meter observation")
        bad_pump = (not pump["on"] or pump_w < limits["min_pump_w"]) if pump_ok else None
        condition(f"{cycle}:pump", gated(bad_pump), config["pump_fault_seconds"],
                  f"Cycle {cycle}: commanded pump is not running",
                  f"Relay={pump.get('on')}; electrical power={pump_w} W; expected ON and >= {limits['min_pump_w']} W")
        flow = number(meter.get("volume_flow_m3h"))
        flow_bad = flow < limits["min_flow_m3h"] if meter_ok else None
        if on_seconds < config["flow_grace_seconds"]:
            flow_bad = None
        condition(f"{cycle}:flow", gated(flow_bad), config["flow_fault_seconds"],
                  f"Cycle {cycle}: insufficient circulation",
                  f"Flow={flow} m3/h; expected >= {limits['min_flow_m3h']} m3/h")
        warming = False
        if meter_ok:
            # Require a genuinely earlier observation, not the previous second.
            older = [r for r in state["history"] if 180 <= now - r["epoch"] <= 360
                     and r["cycles"].get(cycle, {}).get("supply_c") is not None]
            if older:
                old = older[0]["cycles"][cycle]
                warming = meter["flow_temperature_c"] - old["supply_c"] >= limits["warming_rise_c"]
        thermal_bad = None
        if meter_ok and on_seconds >= config["warmup_seconds"]:
            # Hot return water and normal burner cycling alone are not faults.
            thermal_bad = (meter["power_w"] < limits["min_heat_w"]
                           and meter["flow_temperature_c"] < limits["min_supply_c"]
                           and not warming)
        condition(f"{cycle}:heat", gated(thermal_bad), config["thermal_fault_seconds"],
                  f"Cycle {cycle}: heat is not arriving",
                  f"Supply={meter.get('flow_temperature_c')} C; return={meter.get('return_temperature_c')} C; "
                  f"heat={meter.get('power_w')} W; expected supply >= {limits['min_supply_c']} C "
                  f"or heat >= {limits['min_heat_w']} W or a warming trend",
                  config["thermal_bad_checks"])
        summary[cycle] = {"commanded_on": demand, "on_seconds": on_seconds,
                          "pump_on": pump.get("on") if pump_ok else None,
                          "pump_w": pump_w if pump_ok else None,
                          "supply_c": meter.get("flow_temperature_c") if meter_ok else None,
                          "return_c": meter.get("return_temperature_c") if meter_ok else None,
                          "flow_m3h": flow if meter_ok else None,
                          "heat_w": meter.get("power_w") if meter_ok else None}
    demanded = any(v.get("commanded_on") is True for v in summary.values())
    boilers = snapshot.get("boilers", {})
    bad_boilers = [name for name, reading in boilers.items()
                   if not fresh(reading, now, config["reading_max_age_seconds"])
                   or number(reading.get("power_w")) is None or type(reading.get("on")) is not bool]
    condition("monitor:boilers", (bool(bad_boilers) or not boilers) if demanded else False if command_ok else None,
              config["missing_seconds"], "Boiler power measurements unavailable",
              ", ".join(bad_boilers) or "No configured boiler measurements")
    events = []
    for key, (bad, delay, checks, label, detail) in conditions.items():
        incident = state["incidents"].get(key)
        if bad is True:
            candidate = state["candidates"].setdefault(key, {"since": now, "checks": 0})
            candidate["checks"] += 1
            if now - candidate["since"] >= delay and candidate["checks"] >= checks:
                if not incident or not incident["active"]:
                    incident = {"key": key, "opened_at": now, "bad_since": candidate["since"],
                                "active": True, "notified_at": None, "recovered_at": None,
                                "recovery_sent": False, "healthy_since": None}
                    state["incidents"][key] = incident
                    events.append({"event": "opened", "key": key, "epoch": now})
                incident.update(label=label, detail=detail, last_bad_at=now, healthy_since=None)
            elif incident and incident["active"]:
                incident["healthy_since"] = None
        else:
            state["candidates"].pop(key, None)
            if incident and incident["active"]:
                if bad is None:
                    incident["healthy_since"] = None
                else:
                    if incident.get("healthy_since") is None:
                        incident["healthy_since"] = now
                    if now - incident["healthy_since"] >= config["recovery_seconds"]:
                        cycle = key.split(":")[0]
                        reason = ("Heating demand withdrawn" if cycle in summary and
                                  summary[cycle]["commanded_on"] is False else "Healthy observations sustained")
                        incident.update(active=False, recovered_at=now, resolution=reason)
                        events.append({"event": "resolved", "key": key, "epoch": now})
    state["history"] = [r for r in state["history"] if 0 <= now - r["epoch"] <= 900]
    state["history"].append({"epoch": now, "cycles": summary,
                             "boiler_power_w": {name: number(v.get("power_w"))
                                                if fresh(v, now, config["reading_max_age_seconds"]) else None
                                                for name, v in boilers.items()}})
    state["history"] = state["history"][-32:]
    state["last_epoch"] = now
    # Keep only active incidents and recoveries that still need delivery.
    state["incidents"] = {k: v for k, v in state["incidents"].items()
                          if v["active"] or (v["notified_at"] is not None and not v["recovery_sent"])}
    return state, events


def due_notifications(state, now, config):
    result = []
    for key, incident in sorted(state["incidents"].items()):
        sent = incident["notified_at"]
        if incident["active"] and (sent is None or now - sent >= config["reminder_seconds"]):
            result.append({"key": key, "opened_at": incident["opened_at"],
                           "kind": "alert" if sent is None else "reminder"})
        elif not incident["active"] and sent is not None and not incident["recovery_sent"]:
            result.append({"key": key, "opened_at": incident["opened_at"], "kind": "recovery"})
    return result


def mark_delivered(state, events, now):
    for event in events:
        incident = state["incidents"].get(event["key"])
        if not incident or incident["opened_at"] != event["opened_at"]:
            continue
        if event["kind"] == "recovery":
            incident["recovery_sent"] = True
        else:
            incident["notified_at"] = now


def render_report(snapshot, state, events, capture):
    def fmt(value, digits=2):
        value = number(value)
        return "unavailable" if value is None else f"{value:.{digits}f}"
    def when(epoch):
        return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")
    lines = [f"Heating monitor diagnostic at {snapshot['timestamp']}", ""]
    for event in events:
        incident = state["incidents"][event["key"]]
        lines += [f"{event['kind'].upper()}: {incident['label']}",
                  f"Condition observed since {when(incident['bad_since'])}; opened {when(incident['opened_at'])}.",
                  incident["detail"]]
        if event["kind"] == "recovery":
            lines.append(incident["resolution"])
    commands = snapshot["commands"]
    lines += ["", f"Boiler heating command: {commands.get('boiler')}; master switch: {commands.get('master')}",
              f"Command state timestamp: {commands.get('updated_at')}; error: {commands.get('error')}",
              "", "ALL HEATING CYCLES (pump electrical W; heat delivered thermal W)"]
    latest = state["history"][-1]["cycles"]
    for cycle in CYCLES:
        r = latest[cycle]
        lines.append(f"Cycle {cycle} ({snapshot['cycle_names'][cycle]}): command={r['commanded_on']}, "
                     f"continuously requested {r['on_seconds']/60:.1f} min; pump relay={r['pump_on']}, "
                     f"pump={fmt(r['pump_w'])} W; supply={fmt(r['supply_c'])} C, return={fmt(r['return_c'])} C, "
                     f"flow={fmt(r['flow_m3h'],3)} m3/h, heat={fmt(r['heat_w'])} W.")
        p = snapshot["pumps"].get(cycle, {})
        meter = snapshot["heatmeters"].get(str(snapshot["meter_mapping"][cycle]), {})
        lines.append(f"  Pump observed {p.get('observed_at')}, error={p.get('error')}; "
                     f"meter observed {meter.get('observed_at')}, error={meter.get('error')}.")
    lines += ["", "ALL BOILER POWER PLUGS (electrical consumption, not thermal output)"]
    for name, r in snapshot["boilers"].items():
        lines.append(f"{name}: relay={r.get('on')}; power={fmt(r.get('power_w'))} W; "
                     f"observed={r.get('observed_at')}; error={r.get('error')}.")
    lines += ["", "RECENT DIRECT OBSERVATIONS (the monitor's own samples)"]
    for r in state["history"][-16:]:
        lines.append(when(r["epoch"]) + " | " + " | ".join(
            f"C{c} on={v['commanded_on']} pump={fmt(v['pump_w'])}W "
            f"flow={fmt(v['flow_m3h'],3)} supply={fmt(v['supply_c'])}C heat={fmt(v['heat_w'])}W"
            for c, v in r["cycles"].items()) + " | Boilers: " + ", ".join(
                f"{name}={fmt(watts)}W" for name, watts in r.get("boiler_power_w", {}).items()))
    lines += ["", "VISUAL CHECK", capture.get("status", "not requested"),
              capture.get("error") or "", "Machine-readable evidence and available current camera images are attached."]
    return "\n".join(lines)
