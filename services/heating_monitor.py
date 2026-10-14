"""Independent heating monitor using direct device queries, never measurement logs.

Run normally from systemd; --dry-run takes fresh readings without state, logs,
camera captures or email. --test-email sends an explicitly labelled installation
test to the configured admin, with fresh evidence and camera attachments.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from filelock import FileLock, Timeout
from utils.heating_monitor import (
    CYCLES, due_notifications, evaluate, mark_delivered, new_state,
    number, render_report, validate_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/heating_monitor.json"
STATE_DIR = Path("/var/lib/kazanfutes/heating_monitor")
FIELDS = ["flow_temperature_c", "return_temperature_c", "volume_flow_m3h", "power_w"]
MARKER = "HEATING_MONITOR_RESULT "


def stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name, delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    # The controller's existing JSON writer is not atomic.
    for attempt in range(3):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(.1)


def read_commands(config):
    result = {"available": False, "cycles": {}, "boiler": None, "master": None,
              "updated_at": None, "error": None}
    try:
        switch = read_json(ROOT / "config/heating_switch.json")
        master = switch["system"]
        if master not in (0, 1):
            raise ValueError("invalid heating master switch")
        result["master"] = master
        if master == 0:
            result.update(available=True, cycles={c: False for c in CYCLES}, boiler=False,
                          updated_at=stamp())
            return result
        control = read_json(ROOT / "system/control.json")
        updated = datetime.strptime(control["last_updated"], "%Y-%m-%d-%H-%M-%S").astimezone()
        age = time.time() - updated.timestamp()
        if age < -5 or age > config["command_max_age_seconds"]:
            raise ValueError(f"command state is {age:.0f} seconds old")
        if control.get("error"):
            raise ValueError("controller reports an error")
        cycles = control["cycles"]
        if any(type(cycles.get(c)) not in (int, bool) or cycles[c] not in (0, 1) for c in CYCLES):
            raise ValueError("incomplete or invalid cycle commands")
        if control.get("boiler") not in (0, 1):
            raise ValueError("invalid boiler command")
        result.update(available=True, cycles={c: bool(cycles[c]) for c in CYCLES},
                      boiler=bool(control["boiler"]), updated_at=control["last_updated"])
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def observation(**values):
    return dict(epoch=time.time(), observed_at=stamp(), error=None, **values)


def publish(identifier, reading):
    print(MARKER + json.dumps({"id": str(identifier), "reading": reading}, allow_nan=False), flush=True)


def collect_worker(group):
    if group == "pumps":
        from utils.project import connect_to_pump
        for cycle in CYCLES:
            device = None
            try:
                device = connect_to_pump(cycle)
                device.set_socketTimeout(2)
                device.set_socketRetryLimit(1)
                device.set_dpsUsed({"1": None, "19": None})
                response = device.status()
                dps = response.get("dps", {})
                relay = dps.get("1")
                watts = number(dps.get("19"))
                if relay not in (True, False, 0, 1) or watts is None or watts < 0:
                    raise ValueError("pump did not return valid relay and electrical power")
                publish(cycle, observation(on=bool(relay), power_w=watts / 10))
            except Exception as error:
                reading = observation()
                reading["error"] = f"{type(error).__name__}: {error}"
                publish(cycle, reading)
            finally:
                if device is not None:
                    try:
                        device.close()
                    except Exception:
                        pass
    elif group == "heatmeters":
        from utils.project import get_heatmeter_data
        for meter in range(1, 5):
            try:
                raw = get_heatmeter_data(meter, fields=FIELDS)
                values = {k: number(raw.get(k)) for k in FIELDS}
                if any(v is None for v in values.values()):
                    raise ValueError("heat meter returned missing or non-finite values")
                if not all(-20 <= values[k] <= 150 for k in FIELDS[:2]):
                    raise ValueError("heat meter returned implausible water temperature")
                publish(meter, observation(**values))
            except Exception as error:
                reading = observation()
                reading["error"] = f"{type(error).__name__}: {error}"
                publish(meter, reading)
    else:
        from utils.boiler_power import collect_boiler_plugs
        for device in collect_boiler_plugs(str(ROOT)):
            facts = device["facts"]
            reading = observation(on=facts.get("output_on"), **facts.get("measurements", {}))
            reading["error"] = facts.get("collection_error")
            if facts.get("reachable") is not True and not reading["error"]:
                reading["error"] = "boiler plug unreachable"
            publish(device["name"], reading)


def bounded_process(args, timeout):
    """Kill the entire owned process group, including fswebcam, on timeout."""
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = process.communicate(timeout=timeout)
        return process.returncode, out, err
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        out, err = process.communicate()
        return 124, out, f"Timed out after {timeout}s. " + err[-2000:]


def collect_group(group, config):
    result = {}
    try:
        code, out, err = bounded_process(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--collect", group],
            config["collector_timeout_seconds"])
        for line in out.splitlines():
            if line.startswith(MARKER):
                item = json.loads(line[len(MARKER):])
                result[item["id"]] = item["reading"]
        failure = f"{group} collector exit={code}: {err[-1000:]}" if code else "collector did not return this device"
    except Exception as error:
        failure = f"{group} collector: {type(error).__name__}: {error}"
    if group == "boilers":
        try:
            expected = read_json(ROOT / "config/shelly_devices.json")["boiler_power_devices"]
        except Exception:
            expected = ["configured_boiler_plugs"]
    else:
        expected = CYCLES
    for identifier in expected:
        result.setdefault(identifier, {"epoch": time.time(), "observed_at": stamp(), "error": failure})
    return result


def collect_snapshot(config):
    before = read_commands(config)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {group: pool.submit(collect_group, group, config)
                   for group in ("pumps", "heatmeters", "boilers")}
        readings = {group: future.result() for group, future in futures.items()}
    after = read_commands(config)
    # A changed command during collection cannot establish continuous demand.
    if before["available"] and after["available"]:
        for cycle in CYCLES:
            if before["cycles"].get(cycle) != after["cycles"].get(cycle):
                after["cycles"][cycle] = None
    setup = read_json(ROOT / "system/setup.json")
    return {"timestamp": stamp(), "epoch": time.time(), "commands": after,
            "cycle_names": {c: setup["cycles"][c]["name"] for c in CYCLES},
            "meter_mapping": {c: config["cycles"][c]["meter"] for c in CYCLES}, **readings}


def capture_visual(config):
    started = time.time()
    images = []
    try:
        code, out, err = bounded_process(
            [sys.executable, "-B", str(ROOT / "dev/dev_scripts/visual_check.py")],
            config["camera_timeout_seconds"])
        if code:
            return {"status": "failed", "error": f"visual_check exit={code}: {err[-2000:]}", "images": []}
        directory = (ROOT / "data/logs/visual").resolve()
        for line in out.splitlines():
            if line.startswith("Captured ") and ": " in line:
                path = (ROOT / line.split(": ", 1)[1]).resolve()
                if (path.parent != directory or path.suffix.lower() != ".jpg"
                        or path.stat().st_mtime < started - 1 or not 0 < path.stat().st_size < 8_000_000):
                    raise ValueError("visual_check returned an invalid or old image")
                images.append(str(path))
        if len(images) != 2:
            raise ValueError(f"visual_check returned {len(images)} images; expected two")
        return {"status": "success", "error": None, "images": images}
    except Exception as error:
        return {"status": "failed", "error": f"{type(error).__name__}: {error}", "images": []}


def prepare_outbox(snapshot, state, events, config, directory):
    capture = capture_visual(config)
    identity = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    destination = directory / "reports" / identity
    destination.mkdir(parents=True)
    evidence = destination / "diagnostic.json"
    atomic_json(evidence, {"snapshot": snapshot, "history": state["history"],
                          "incidents": state["incidents"], "events": events,
                          "limits": config, "visual_check": capture})
    kinds = {e["kind"] for e in events}
    heading = "RECOVERY" if kinds == {"recovery"} else "ALERT"
    if kinds == {"test"}:
        heading = "INSTALLATION TEST - no fault asserted"
    captured_images = []
    for image in capture["images"]:
        archived = destination / Path(image).name
        shutil.copyfile(image, archived)
        captured_images.append(str(archived))
    manifest = {"events": events, "subject": f"[Heating monitor] {heading}",
                "body": render_report(snapshot, state, events, capture),
                "attachments": [str(evidence), *captured_images], "next_retry_at": 0,
                "created_at": snapshot["epoch"]}
    atomic_json(destination / "mail.json", manifest)
    manifest["path"] = str(destination / "mail.json")
    return manifest


def deliver_worker(manifest_path, timeout):
    from utils.project import send_email, settings
    manifest = read_json(manifest_path)
    success = send_email(settings["admin_email"], subject=manifest["subject"],
                         body=manifest["body"], attachments=manifest["attachments"],
                         timeout=timeout)
    if not success:
        raise RuntimeError("email was not accepted")
    print("HEATING_MONITOR_MAIL_ACCEPTED", flush=True)


def deliver(outbox, config):
    code, out, err = bounded_process(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--deliver", outbox["path"]],
        config["email_timeout_seconds"])
    return code == 0 and "HEATING_MONITOR_MAIL_ACCEPTED" in out, err[-2000:]


def log_observation(snapshot, events, state):
    path = ROOT / "data/logs/heating_monitor/observations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("heating_monitor.observations")
    logger.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler(path, when="midnight", backupCount=90, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    try:
        logger.info(json.dumps({"snapshot": snapshot, "events": events,
                               "incidents": state["incidents"]}, ensure_ascii=False, allow_nan=False))
    finally:
        logger.removeHandler(handler)
        handler.close()


def run(config, directory, dry_run=False, test_email=False):
    snapshot = collect_snapshot(config)
    state_path = directory / "state.json"
    try:
        previous = read_json(state_path)
        if not isinstance(previous, dict):
            raise ValueError("state is not an object")
    except FileNotFoundError:
        previous = new_state()
    except (ValueError, OSError) as error:
        print(f"Monitor state unavailable; restarting observation timers: {error}", flush=True)
        previous = new_state()
    try:
        state, changes = evaluate(previous, snapshot, config)
    except (KeyError, TypeError, ValueError):
        print("Invalid saved monitor state; restarting observation timers.", flush=True)
        state, changes = evaluate(new_state(), snapshot, config)
    if dry_run:
        print(json.dumps({"snapshot": snapshot, "incidents": state["incidents"],
                          "history": state["history"][-1:]}, ensure_ascii=False, indent=2))
        return 0
    if test_email:
        key = "installation:test"
        state = new_state()
        state, _ = evaluate(state, snapshot, config)
        state["incidents"][key] = {
            "key": key, "opened_at": snapshot["epoch"], "bad_since": snapshot["epoch"],
            "label": "Installation test; no heating fault is asserted",
            "detail": "Fresh measurements and both visual-check cameras are being tested.",
            "active": True, "notified_at": None}
        events = [{"key": key, "opened_at": snapshot["epoch"], "kind": "test"}]
        outbox = prepare_outbox(snapshot, state, events, config, directory)
        ok, error = deliver(outbox, config)
        print(json.dumps({"test_email_accepted": ok, "error": error, "evidence": outbox["attachments"]}))
        return 0 if ok else 1
    log_observation(snapshot, changes, state)
    due = due_notifications(state, snapshot["epoch"], config)
    # Persist timers before any slow camera/email operation.
    atomic_json(state_path, state)
    if config["mode"] == "live" and due:
        pending = state.get("outbox")
        if not pending or pending["events"] != due:
            state["outbox"] = prepare_outbox(snapshot, state, due, config, directory)
            atomic_json(state_path, state)
        pending = state["outbox"]
        if time.time() >= pending["next_retry_at"]:
            ok, error = deliver(pending, config)
            if ok:
                mark_delivered(state, due, time.time())
                state["outbox"] = None
            else:
                pending["next_retry_at"] = time.time() + config["retry_seconds"]
                print(f"Email deferred for retry: {error}", flush=True)
            atomic_json(state_path, state)
    elif not due:
        state["outbox"] = None
        atomic_json(state_path, state)
    print(json.dumps({"timestamp": snapshot["timestamp"], "mode": config["mode"],
                      "active_incidents": [k for k, v in state["incidents"].items() if v["active"]],
                      "events": changes, "email_pending": state.get("outbox") is not None}), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", choices=("pumps", "heatmeters", "boilers"))
    parser.add_argument("--deliver", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-email", action="store_true")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    args = parser.parse_args()
    if args.collect:
        collect_worker(args.collect)
        return 0
    config = read_json(CONFIG)
    validate_config(config)
    if args.deliver:
        deliver_worker(args.deliver, min(10, config["email_timeout_seconds"]))
        return 0
    if args.dry_run:
        return run(config, args.state_dir, dry_run=True)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(args.state_dir / "monitor.lock"), timeout=0):
            return run(config, args.state_dir, test_email=args.test_email)
    except Timeout:
        print("Another heating-monitor run is active; skipping.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
