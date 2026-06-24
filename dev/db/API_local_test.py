import db_queries
import sys


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


TEST_SCOPE_TYPE = "room"
TEST_SCOPE_ID = "1"
TEST_VARIABLES = ["set_temperature"]

RAW_FROM = "2025-11-01 00:00:00"
RAW_TO = "2025-11-01 06:00:00"

SUMMARY_FROM = "2025-11-01 00:00:00"
SUMMARY_TO = "2025-11-08 00:00:00"


def print_rows(title, rows, limit=5):
    print()
    print(title)
    print("-" * len(title))

    for row in rows[:limit]:
        print(row)

    if len(rows) > limit:
        print(f"... {len(rows) - limit} more rows")


def print_test_settings():
    print("Local API sandbox")
    print("=================")
    print("scope_type:", TEST_SCOPE_TYPE)
    print("scope_id:", TEST_SCOPE_ID)
    print("variables:", TEST_VARIABLES)
    print("raw range:", RAW_FROM, "to", RAW_TO)
    print("summary range:", SUMMARY_FROM, "to", SUMMARY_TO)


def main():
    streams = db_queries.get_streams()
    availability = db_queries.get_stream_availability()

    room_1_availability = [
        row for row in availability
        if row["stream_id"] in ["room.1.temperature", "room.1.humidity"]
    ]

    observations = db_queries.query_observations(
        from_=RAW_FROM,
        to=RAW_TO,
        variables=TEST_VARIABLES,
        scope_type=TEST_SCOPE_TYPE,
        scope_id=TEST_SCOPE_ID,
    )

    hourly_summary = db_queries.query_summary(
        from_=SUMMARY_FROM,
        to=SUMMARY_TO,
        variables=TEST_VARIABLES,
        scope_type=TEST_SCOPE_TYPE,
        scope_id=TEST_SCOPE_ID,
        bin_="hour",
    )

    daily_summary = db_queries.query_summary(
        from_=SUMMARY_FROM,
        to=SUMMARY_TO,
        variables=TEST_VARIABLES,
        scope_type=TEST_SCOPE_TYPE,
        scope_id=TEST_SCOPE_ID,
        bin_="day",
    )

    observations_grouped = db_queries.query_observations_grouped(
        from_=RAW_FROM,
        to=RAW_TO,
        variables=TEST_VARIABLES,
        scope_type=TEST_SCOPE_TYPE,
        scope_id=TEST_SCOPE_ID,
        bin_="hour",
    )

    hourly_mean_wide = db_queries.query_summary_wide(
        from_=SUMMARY_FROM,
        to=SUMMARY_TO,
        variables=TEST_VARIABLES,
        scope_type=TEST_SCOPE_TYPE,
        scope_id=TEST_SCOPE_ID,
        bin_="hour",
        metric="mean_value",
        decimal_places=4
    )

    print_test_settings()
    print()
    print("stream count:", len(streams))
    print("availability row count:", len(availability))
    print("observation query row count:", len(observations))
    print("hourly summary row count:", len(hourly_summary))
    print("daily summary row count:", len(daily_summary))
    print("grouped observation bin count:", len(observations_grouped))
    print("wide hourly mean row count:", len(hourly_mean_wide))

    print_rows(
        "room.1 availability",
        room_1_availability,
    )
    print_rows("raw observations", observations, limit=10)
    print_rows("grouped raw observations", observations_grouped, limit=3)
    print_rows("hourly summary", hourly_summary, limit=24)
    print_rows("daily summary", daily_summary, limit=10)
    print_rows("wide hourly mean summary", hourly_mean_wide, limit=24)


if __name__ == "__main__":
    main()
