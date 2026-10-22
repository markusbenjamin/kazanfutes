"""Schedule interpolation and the room target used before the PID overlay.

Pure functions: safe to use in formatting and offline regression tests.
"""


def interpolate_set_temperature(schedule, unix_day, hour, hour_fraction,
                                window_hours=3, lookahead_hours=24):
    """Ramp upward within the current plateau; leave downward steps immediate.

    Only available schedule history is used. At the start of the available
    schedule, the first known hour is the earliest possible ramp start.
    """
    def value_at(offset):
        day_offset, slot = divmod(hour + offset, 24)
        return schedule.get(str(unix_day + day_offset), {}).get(str(slot))

    current = value_at(0)
    for ahead in range(1, lookahead_hours + 1):
        following = value_at(ahead)
        if following is None:
            return current
        if following != current:
            break
    else:
        return current

    if following <= current:
        return current

    # A three-hour ramp must not start before this plateau starts. Looking
    # back one window is sufficient even for a plateau lasting many days.
    plateau_start = 0
    for back in range(1, window_hours + 1):
        if value_at(-back) != current:
            break
        plateau_start = -back
    ramp_start = max(ahead - window_hours, plateau_start)
    fraction = max(0.0, min(1.0, (hour_fraction - ramp_start) /
                           (ahead - ramp_start)))
    return current + (following - current) * fraction


def room_control_set_temperature(state, room):
    """Read the actual upward-only target, including older nominal-only logs."""
    nominal = state['set_temps'][room]
    interpolated = state.get('set_temps_interp', {}).get(room)
    return nominal if interpolated is None else max(nominal, interpolated)


def schedule_with_recent_history(schedule, history, unix_day, hour):
    """Retain three past hours when the daily schedule drops yesterday.

    Current schedule entries always win over remembered entries, so occupancy
    and manual changes still take effect immediately.
    """
    combined = {day: dict(values) for day, values in schedule.items()}
    recent = {}
    for back in range(4):
        absolute_hour = unix_day * 24 + hour - back
        day, slot = divmod(absolute_hour, 24)
        values = combined.setdefault(str(day), {})
        key = str(absolute_hour)
        if str(slot) not in values and back > 0 and key in history:
            values[str(slot)] = history[key]
        if str(slot) in values:
            recent[key] = values[str(slot)]
    return combined, recent
