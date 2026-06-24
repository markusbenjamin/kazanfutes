import csv
from pathlib import Path


BASE_PATH = Path(__file__).resolve().parent

SCOPE_METADATA_PATH = BASE_PATH / "scope_metadata.csv"
SCOPE_LIST_PATH = BASE_PATH / "scope_list.csv"
VARIABLE_LIST_PATH = BASE_PATH / "variable_list.csv"
STREAM_METADATA_PATH = BASE_PATH / "stream_metadata.csv"

VARIABLE_DESCRIPTION_LABELS = {
    "co2": "CO2",
}


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def read_scope_variables():
    rows = read_csv(SCOPE_METADATA_PATH)
    scope_variables = {}

    for row in rows:
        scope_type = row["scope_type"]
        variables = [
            variable.strip()
            for variable in row["variables"].split(";")
            if variable.strip()
        ]
        scope_variables[scope_type] = variables

    return scope_variables


def read_variable_units():
    rows = read_csv(VARIABLE_LIST_PATH)
    return {
        row["variable"]: row["unit"]
        for row in rows
    }


def validate_inputs(scopes, scope_variables, variable_units):
    errors = []

    for scope in scopes:
        scope_type = scope["scope_type"]
        if scope_type not in scope_variables:
            errors.append(f"scope_list has unknown scope_type: {scope_type}")

    for scope_type, variables in scope_variables.items():
        for variable in variables:
            if variable not in variable_units:
                errors.append(
                    f"scope_metadata references unknown variable: {scope_type}.{variable}"
                )

    seen_scopes = set()
    for scope in scopes:
        key = (scope["scope_type"], scope["scope_id"])
        if key in seen_scopes:
            errors.append(f"duplicate scope: {scope['scope_type']}.{scope['scope_id']}")
        seen_scopes.add(key)

    if errors:
        raise ValueError("\n".join(errors))


def make_stream_id(scope_type, scope_id, variable):
    return f"{scope_type}.{scope_id}.{variable}"


def make_stream_description(scope_description, variable):
    variable_label = VARIABLE_DESCRIPTION_LABELS.get(variable, variable)
    return f"{scope_description} - {variable_label}"


def generate_streams():
    scopes = read_csv(SCOPE_LIST_PATH)
    scope_variables = read_scope_variables()
    variable_units = read_variable_units()

    validate_inputs(scopes, scope_variables, variable_units)

    streams = []
    seen_stream_ids = set()

    for scope in scopes:
        scope_type = scope["scope_type"]
        scope_id = scope["scope_id"]
        scope_description = scope["description"]

        for variable in scope_variables[scope_type]:
            stream_id = make_stream_id(scope_type, scope_id, variable)

            if stream_id in seen_stream_ids:
                raise ValueError(f"duplicate stream_id: {stream_id}")

            seen_stream_ids.add(stream_id)
            streams.append({
                "stream_id": stream_id,
                "variable": variable,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "unit": variable_units[variable],
                "description": make_stream_description(scope_description, variable),
            })

    return streams


def write_streams(streams):
    fieldnames = [
        "stream_id",
        "variable",
        "scope_type",
        "scope_id",
        "unit",
        "description",
    ]

    with STREAM_METADATA_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(streams)


def main():
    streams = generate_streams()
    write_streams(streams)
    print(f"wrote {STREAM_METADATA_PATH}")
    print(f"stream count: {len(streams)}")


if __name__ == "__main__":
    main()
