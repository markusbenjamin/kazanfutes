"""Room measurement policies for the inactive room-ID release candidate."""
import math


def is_nous_source(source):
    name = str(source).strip().casefold()
    return name.startswith('nous') or name.startswith('deconz/nous')


def averaging_sources(sources):
    """Nous observations must never participate in an average."""
    return list(dict.fromkeys(source for source in sources if not is_nous_source(source)))


def average_non_nous(readings):
    values = [readings[name] for name in averaging_sources(readings)
              if not isinstance(readings[name], bool)
              and isinstance(readings[name], (int, float))
              and math.isfinite(readings[name])]
    return sum(values) / len(values) if values else None


def presence_sources_by_room(rooms):
    """Collect presence for every included room, independently of control."""
    result = {}
    for room, config in rooms.items():
        if config.get('included', True) is False:
            continue
        names = config.get('presence_sensors')
        result[str(room)] = list(dict.fromkeys(names)) if isinstance(names, list) else []
    return result


def room_presence_states(rooms, observations):
    """Combine already health/freshness-normalized sensor states.

    A positive observation establishes presence. Absence requires every assigned
    source to report false. Unknown readings or removed sensors clear old striping.
    This function cannot enable room control or emit a heating command.
    """
    result = {}
    for room, names in presence_sources_by_room(rooms).items():
        values = [observations.get(name) for name in names]
        result[room] = (True if any(value is True for value in values)
                        else False if values and all(value is False for value in values)
                        else None)
    return result
