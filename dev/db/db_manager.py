import html

import duckdb


MODE = "write_stream_timeline"

DATA_PATH = __file__.replace("\\", "/").rsplit("/", 2)[0]
DB_PATH = f"{DATA_PATH}/db/store/observations.duckdb"
STREAM_METADATA_PATH = f"{DATA_PATH}/db/metadata/stream_metadata.csv"
TIMELINE_PATH = f"{DATA_PATH}/db/stream_availability.html"
AVAILABILITY_CSV_PATH = f"{DATA_PATH}/db/stream_availability.csv"


def connect():
    return duckdb.connect(DB_PATH)


def table_exists(con, table_name):
    return con.execute("""
    SELECT count(*)
    FROM information_schema.tables
    WHERE table_name = ?;
    """, [table_name]).fetchone()[0] > 0


def column_exists(con, table_name, column_name):
    return con.execute("""
    SELECT count(*)
    FROM information_schema.columns
    WHERE table_name = ?
      AND column_name = ?;
    """, [table_name, column_name]).fetchone()[0] > 0


def migrate_series_to_streams(con):
    if table_exists(con, "series") and not table_exists(con, "streams"):
        con.execute("ALTER TABLE series RENAME TO streams;")

    if table_exists(con, "streams") and column_exists(con, "streams", "series_id"):
        con.execute("ALTER TABLE streams RENAME COLUMN series_id TO stream_id;")

    if table_exists(con, "observations") and column_exists(con, "observations", "series_id"):
        con.execute("ALTER TABLE observations RENAME COLUMN series_id TO stream_id;")


def drop_source_from_streams(con):
    if table_exists(con, "streams") and column_exists(con, "streams", "source"):
        con.execute("ALTER TABLE streams DROP COLUMN source;")


def migrate_observation_timestamp_column(con):
    if (
        table_exists(con, "observations")
        and column_exists(con, "observations", "timestamp_utc")
        and not column_exists(con, "observations", "timestamp")
    ):
        con.execute("DROP VIEW IF EXISTS stream_availability;")
        con.execute("ALTER TABLE observations RENAME COLUMN timestamp_utc TO timestamp;")
        con.execute("""
        UPDATE observations
        SET "timestamp" = ("timestamp" AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Budapest';
        """)


def init_db():
    con = connect()

    migrate_series_to_streams(con)
    drop_source_from_streams(con)
    migrate_observation_timestamp_column(con)

    con.execute("""
    CREATE TABLE IF NOT EXISTS streams (
        stream_id TEXT PRIMARY KEY,
        variable TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        unit TEXT,
        description TEXT
    );
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS observations (
        "timestamp" TIMESTAMP NOT NULL,
        stream_id TEXT NOT NULL,
        value DOUBLE NOT NULL
    );
    """)

    con.execute("""
    CREATE OR REPLACE VIEW stream_availability AS
    SELECT
        st.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit,
        min(o."timestamp") AS first_observation,
        max(o."timestamp") AS last_observation,
        count(o."timestamp") AS observation_count
    FROM streams AS st
    LEFT JOIN observations AS o
        ON st.stream_id = o.stream_id
    GROUP BY
        st.stream_id,
        st.variable,
        st.scope_type,
        st.scope_id,
        st.unit;
    """)

    con.close()

    print("initialized", DB_PATH)


def load_stream_metadata():
    con = connect()

    con.execute("""
    CREATE TEMP TABLE loaded_streams AS
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    FROM read_csv_auto(?);
    """, [STREAM_METADATA_PATH])

    con.execute("""
    DELETE FROM streams
    USING loaded_streams
    WHERE streams.stream_id = loaded_streams.stream_id;
    """)

    con.execute("""
    INSERT INTO streams (
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    )
    SELECT
        stream_id,
        variable,
        scope_type,
        scope_id,
        unit,
        description
    FROM loaded_streams
    ORDER BY scope_type, scope_id, variable, stream_id;
    """)

    stream_count = con.execute("SELECT count(*) FROM streams;").fetchone()[0]
    con.close()

    print("loaded stream metadata", STREAM_METADATA_PATH)
    print("stream count:", stream_count)


def show_stream_availability():
    con = connect()

    rows = con.execute("""
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
    """).fetchall()

    con.close()

    if not rows:
        print("stream_availability is empty")
        return

    for row in rows:
        print(row)


def fetch_stream_availability():
    con = connect()

    rows = con.execute("""
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
    """).fetchall()

    con.close()
    return rows


def format_value(value):
    if value is None:
        return ""
    return html.escape(str(value))


def write_stream_timeline():
    rows = fetch_stream_availability()
    observed_rows = [
        row for row in rows
        if row[5] is not None and row[6] is not None and row[7] > 0
    ]

    if observed_rows:
        timeline_start = min(row[5] for row in observed_rows)
        timeline_end = max(row[6] for row in observed_rows)
    else:
        timeline_start = None
        timeline_end = None

    total_seconds = None
    if timeline_start is not None and timeline_end is not None:
        total_seconds = (timeline_end - timeline_start).total_seconds()

    lines = [
        "<!doctype html>",
        "<html>",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<title>Stream availability</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; margin: 24px; color: #202124; }",
        "h1 { font-size: 22px; margin: 0 0 6px; }",
        ".meta { color: #5f6368; margin-bottom: 24px; }",
        ".axis { display: flex; justify-content: space-between; margin: 0 0 10px 280px; color: #5f6368; font-size: 12px; }",
        ".row { display: grid; grid-template-columns: 260px 1fr 80px; gap: 20px; align-items: center; min-height: 34px; border-top: 1px solid #e8eaed; }",
        ".label { overflow-wrap: anywhere; }",
        ".name { font-size: 13px; font-weight: 700; }",
        ".details { color: #5f6368; font-size: 12px; }",
        ".track { position: relative; height: 12px; background: #f1f3f4; border-radius: 6px; }",
        ".bar { position: absolute; height: 12px; min-width: 2px; background: #1a73e8; border-radius: 6px; }",
        ".empty { color: #9aa0a6; font-size: 12px; }",
        ".count { color: #5f6368; font-size: 12px; text-align: right; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Stream availability</h1>",
    ]

    if timeline_start is None:
        lines.append("<div class=\"meta\">No observations found yet.</div>")
    else:
        lines.append(
            f"<div class=\"meta\">{format_value(timeline_start)} to {format_value(timeline_end)}</div>"
        )
        lines.append(
            f"<div class=\"axis\"><span>{format_value(timeline_start)}</span><span>{format_value(timeline_end)}</span></div>"
        )

    if not rows:
        lines.append("<p>No streams found yet.</p>")

    for row in rows:
        stream_id, variable, scope_type, scope_id, unit, first_observation, last_observation, observation_count = row

        label = f"{variable} / {scope_type}:{scope_id}"
        if unit:
            label += f" ({unit})"

        lines.append("<div class=\"row\">")
        lines.append("<div class=\"label\">")
        lines.append(f"<div class=\"name\">{format_value(label)}</div>")
        lines.append(f"<div class=\"details\">{format_value(stream_id)}</div>")
        lines.append("</div>")

        if first_observation is None or last_observation is None or observation_count == 0:
            lines.append("<div class=\"empty\">no observations</div>")
        elif total_seconds == 0:
            lines.append("<div class=\"track\"><div class=\"bar\" style=\"left: 0%; width: 100%;\"></div></div>")
        else:
            start_percent = 100 * (first_observation - timeline_start).total_seconds() / total_seconds
            end_percent = 100 * (last_observation - timeline_start).total_seconds() / total_seconds
            width_percent = max(end_percent - start_percent, 0.5)
            lines.append(
                "<div class=\"track\">"
                f"<div class=\"bar\" title=\"{format_value(first_observation)} to {format_value(last_observation)}\" "
                f"style=\"left: {start_percent:.3f}%; width: {width_percent:.3f}%;\"></div>"
                "</div>"
            )

        lines.append(f"<div class=\"count\">{observation_count}</div>")
        lines.append("</div>")

    lines.extend([
        "</body>",
        "</html>",
    ])

    with open(TIMELINE_PATH, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    print("wrote", TIMELINE_PATH)


def write_stream_availability_csv():
    con = connect()

    con.execute("""
    COPY (
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
        ORDER BY scope_type, scope_id, variable, stream_id
    )
    TO ?
    WITH (HEADER, DELIMITER ',');
    """, [AVAILABILITY_CSV_PATH])

    con.close()

    print("wrote", AVAILABILITY_CSV_PATH)


def main():
    if MODE == "init":
        init_db()
    elif MODE == "load_stream_metadata":
        load_stream_metadata()
    elif MODE == "show_stream_availability":
        show_stream_availability()
    elif MODE == "write_stream_timeline":
        write_stream_timeline()
    elif MODE == "write_stream_availability_csv":
        write_stream_availability_csv()
    else:
        print("unknown MODE:", MODE)


if __name__ == "__main__":
    main()
