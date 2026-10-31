"""Interpret FusionSolar's explicit inverter status, independently of production."""

from datetime import datetime, timezone


# Signal 10025 and code 40960 were verified against this inverter's device page:
# "Inverter status: Standby : no sunlight". Other standby/shutdown codes are not
# assumed to mean normal darkness.
INVERTER_STATUS_SIGNAL_ID = 10025
NO_SUNLIGHT_STATUS_CODE = 40960


def no_sunlight_standby(record: dict) -> bool:
    return (
        record.get("inverter_connected") is True
        and record.get("inverter_operating_state_code") == NO_SUNLIGHT_STATUS_CODE
    )


def parse_operating_status(payload: dict, connected: bool) -> dict:
    """Read the native device-realtime-data response without inventing a state."""
    if not isinstance(connected, bool):
        raise ValueError("Missing inverter connection status")
    if connected is False:
        return {"inverter_connected": False}
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Inverter operating-status request failed")
    groups = payload.get("data")
    if not isinstance(groups, list):
        raise ValueError("Missing inverter operating-status data")
    for group in groups:
        if not isinstance(group, dict):
            continue
        signals = group.get("signals", [])
        if not isinstance(signals, list):
            continue
        for signal in signals:
            if not isinstance(signal, dict) or str(signal.get("id")) != str(INVERTER_STATUS_SIGNAL_ID):
                continue
            try:
                code = int(str(signal["realValue"]))
                source_time = datetime.fromtimestamp(float(signal["latestTime"]), timezone.utc)
            except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
                raise ValueError("Invalid inverter operating status") from error
            return {
                "inverter_connected": True,
                "inverter_operating_state_code": code,
                "inverter_operating_state": signal.get("value"),
                # This is the signal's source time, not the time of our query.
                "inverter_state_source_timestamp": source_time.isoformat(timespec="seconds"),
            }
    raise ValueError("Inverter operating-status signal is missing")
