from pathlib import Path

import duckdb


SCRIPT_PATH = Path(__file__).resolve()
DEV_PATH = SCRIPT_PATH.parent.parent
DB_PATH = DEV_PATH / "db" / "store" / "observations.duckdb"


def connect():
    return duckdb.connect(str(DB_PATH), read_only=True)


def rows_as_dicts(cursor):
    columns = [column[0] for column in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def placeholders(values):
    return ", ".join(["?"] * len(values))


def validate_variables(variables):
    if not variables:
        raise ValueError("variables must contain at least one variable")


def bin_sql(bin_):
    allowed_bins = {
        "hour": "hour",
        "day": "day",
    }

    if bin_ not in allowed_bins:
        allowed = ", ".join(sorted(allowed_bins))
        raise ValueError(f"bin must be one of: {allowed}")

    return allowed_bins[bin_]


def validate_decimal_places(decimal_places):
    if not isinstance(decimal_places, int):
        raise ValueError("decimal_places must be an integer")

    if decimal_places < 0 or decimal_places > 6:
        raise ValueError("decimal_places must be between 0 and 6")

    return decimal_places


def stream_filter(scope_type, variables, scope_id=None):
    validate_variables(variables)

    params = [scope_type, *variables]
    scope_filter = ""

    if scope_id is not None:
        scope_filter = "AND scope_id = ?"
        params.append(scope_id)

    return scope_filter, params


def get_streams():
    con = connect()

    cursor = con.execute("""
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    FROM streams
    ORDER BY scope_type, scope_id, variable, stream_id;
    """)

    rows = rows_as_dicts(cursor)
    con.close()
    return rows


def get_stream_availability():
    con = connect()

    cursor = con.execute("""
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        first_observation,
        last_observation,
        observation_count
    FROM stream_availability
    ORDER BY scope_type, scope_id, variable, stream_id;
    """)

    rows = rows_as_dicts(cursor)
    con.close()
    return rows


def get_matching_streams(variables, scope_type, scope_id=None):
    scope_filter, params = stream_filter(scope_type, variables, scope_id)

    con = connect()

    cursor = con.execute(f"""
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    FROM streams
    WHERE scope_type = ?
      AND variable IN ({placeholders(variables)})
      {scope_filter}
    ORDER BY scope_type, scope_id, variable, stream_id;
    """, params)

    rows = rows_as_dicts(cursor)
    con.close()
    return rows


def query_observations(from_, to, variables, scope_type, scope_id=None):
    validate_variables(variables)

    params = [from_, to, scope_type, *variables]
    scope_filter = ""

    if scope_id is not None:
        scope_filter = "AND st.scope_id = ?"
        params.append(scope_id)

    con = connect()

    cursor = con.execute(f"""
    SELECT
        o."timestamp" AS "timestamp",
        o.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit,
        o.value
    FROM observations AS o
    JOIN streams AS st
        ON o.stream_id = st.stream_id
    WHERE o."timestamp" >= ?
      AND o."timestamp" < ?
      AND st.scope_type = ?
      AND st.variable IN ({placeholders(variables)})
      {scope_filter}
    ORDER BY o."timestamp", o.stream_id;
    """, params)

    rows = rows_as_dicts(cursor)
    con.close()
    return rows


def pivot_stream_rows(rows, time_column, value_column, stream_ids):
    rows_by_time = {}

    for row in rows:
        time_value = row[time_column]

        if time_value not in rows_by_time:
            rows_by_time[time_value] = {time_column: time_value}
            for stream_id in stream_ids:
                rows_by_time[time_value][stream_id] = None

        rows_by_time[time_value][row["stream_id"]] = row[value_column]

    return [rows_by_time[time_value] for time_value in sorted(rows_by_time)]


def query_observations_grouped(from_, to, variables, scope_type, scope_id=None, bin_="hour"):
    validate_variables(variables)
    bin_ = bin_sql(bin_)

    streams = get_matching_streams(variables, scope_type, scope_id)
    stream_ids = [stream["stream_id"] for stream in streams]

    params = [from_, to, scope_type, *variables]
    scope_filter = ""

    if scope_id is not None:
        scope_filter = "AND st.scope_id = ?"
        params.append(scope_id)

    con = connect()

    cursor = con.execute(f"""
    SELECT
        date_trunc('{bin_}', o."timestamp") AS bin_start,
        date_trunc('{bin_}', o."timestamp") + INTERVAL 1 {bin_} AS bin_end,
        o."timestamp" AS "timestamp",
        o.stream_id,
        o.value
    FROM observations AS o
    JOIN streams AS st
        ON o.stream_id = st.stream_id
    WHERE o."timestamp" >= ?
      AND o."timestamp" < ?
      AND st.scope_type = ?
      AND st.variable IN ({placeholders(variables)})
      {scope_filter}
    ORDER BY bin_start, o.stream_id, o."timestamp";
    """, params)

    rows = rows_as_dicts(cursor)
    con.close()

    grouped_rows = {}

    for row in rows:
        bin_start = row["bin_start"]

        if bin_start not in grouped_rows:
            grouped_rows[bin_start] = {
                "bin_start": bin_start,
                "bin_end": row["bin_end"],
                "streams": {stream_id: [] for stream_id in stream_ids},
            }

        grouped_rows[bin_start]["streams"][row["stream_id"]].append({
            "timestamp": row["timestamp"],
            "value": row["value"],
        })

    return [grouped_rows[bin_start] for bin_start in sorted(grouped_rows)]


def query_summary(
    from_,
    to,
    variables,
    scope_type,
    scope_id=None,
    bin_="hour",
    decimal_places=1,
):
    validate_variables(variables)
    bin_ = bin_sql(bin_)
    decimal_places = validate_decimal_places(decimal_places)

    params = [from_, to, scope_type, *variables]
    scope_filter = ""

    if scope_id is not None:
        scope_filter = "AND st.scope_id = ?"
        params.append(scope_id)

    con = connect()

    cursor = con.execute(f"""
    SELECT
        date_trunc('{bin_}', o."timestamp") AS bin_start,
        o.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit,
        round(avg(o.value), {decimal_places}) AS mean_value,
        round(min(o.value), {decimal_places}) AS min_value,
        round(max(o.value), {decimal_places}) AS max_value,
        round(stddev_samp(o.value), {decimal_places}) AS stddev_value,
        count(*) AS observation_count
    FROM observations AS o
    JOIN streams AS st
        ON o.stream_id = st.stream_id
    WHERE o."timestamp" >= ?
      AND o."timestamp" < ?
      AND st.scope_type = ?
      AND st.variable IN ({placeholders(variables)})
      {scope_filter}
    GROUP BY
        bin_start,
        o.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit
    ORDER BY bin_start, o.stream_id;
    """, params)

    rows = rows_as_dicts(cursor)
    con.close()
    return rows


def query_summary_wide(
    from_,
    to,
    variables,
    scope_type,
    scope_id=None,
    bin_="hour",
    metric="mean_value",
    decimal_places=1,
):
    allowed_metrics = {
        "mean_value",
        "min_value",
        "max_value",
        "stddev_value",
        "observation_count",
    }

    if metric not in allowed_metrics:
        allowed = ", ".join(sorted(allowed_metrics))
        raise ValueError(f"metric must be one of: {allowed}")

    streams = get_matching_streams(variables, scope_type, scope_id)
    stream_ids = [stream["stream_id"] for stream in streams]

    rows = query_summary(
        from_=from_,
        to=to,
        variables=variables,
        scope_type=scope_type,
        scope_id=scope_id,
        bin_=bin_,
        decimal_places=decimal_places,
    )

    return pivot_stream_rows(
        rows=rows,
        time_column="bin_start",
        value_column=metric,
        stream_ids=stream_ids,
    )
