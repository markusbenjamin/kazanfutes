"""Evaluate room presence without conflating room eligibility with control."""
from utils.occupancy import calculate_occupancy


def room_presence_observations(rooms, sensor_observations):
    result = {}
    for room, info in rooms.items():
        names = info.get('presence_sensors') or []
        if len(names) == 1:
            result[str(room)] = sensor_observations.get(names[0])
        elif names:
            result[str(room)] = {'sources': {name: sensor_observations.get(name) for name in names}}
        else:
            result[str(room)] = None
    return result


def calculate_room_occupancy(logs, rooms, targets, **options):
    """Keep source-specific PIR/radar health semantics, then combine room sources."""
    sources = {}
    pseudo_rooms = {}
    for room, info in rooms.items():
        names = info.get('presence_sensors')
        if names is None:
            names = [info['pres']] if info.get('pres') else []
        sources[str(room)] = list(dict.fromkeys(names))
        for index, name in enumerate(sources[str(room)]):
            pseudo_rooms[f'{room}:{index}'] = {'pres': name}
    expanded = []
    for entry in logs:
        if not isinstance(entry, dict) or not isinstance(entry.get('states'), dict):
            continue
        states = {}
        for room, names in sources.items():
            observation = entry['states'].get(room)
            for index, name in enumerate(names):
                if isinstance(observation, dict) and 'sources' in observation:
                    row = (observation.get('sources') or {}).get(name)
                else:
                    row = observation if index == 0 or (isinstance(observation, dict)
                        and observation.get('source_name') == name) else None
                if isinstance(row, dict):
                    states[f'{room}:{index}'] = row
        expanded.append({**entry, 'states': states})
    evaluated = calculate_occupancy(expanded, pseudo_rooms, targets, **options)
    result = []
    for values in evaluated:
        rooms_at_time = {}
        for room, names in sources.items():
            observations = [values.get(f'{room}:{index}') for index in range(len(names))]
            rooms_at_time[room] = (True if any(value is True for value in observations)
                else False if observations and all(value is False for value in observations)
                else None)
        result.append(rooms_at_time)
    return result
