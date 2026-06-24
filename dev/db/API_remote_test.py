import sys

from db_client import DbApi, DbApiError


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


API_BASE_URL = "http://127.0.0.1:8765"


def print_rows(title, rows, limit=5):
    print()
    print(title)
    print("-" * len(title))

    for row in rows[:limit]:
        print(row)

    if len(rows) > limit:
        print(f"... {len(rows) - limit} more rows")


def main():
    api = DbApi(API_BASE_URL)

    print("Remote API sandbox")
    print("==================")
    print("base URL:", API_BASE_URL)

    try:
        print("health:", api.health())
    except DbApiError as error:
        print("could not reach remote API server")
        print(error)
        print()
        print("Start the server in another terminal:")
        print("python dev/db/db_server.py")
        return

    availability = api.get_stream_availability()
    loaded = [row for row in availability if row["observation_count"] > 0]
    print("loaded stream count:", len(loaded))

    summary = api.query_summary(
        from_="2025-11-01 00:00:00",
        to="2025-11-01 01:00:00",
        variables=["state"],
        scope_type="heating",
        scope_id="main",
        bin_="hour",
        decimal_places=3,
    )

    wide = api.query_summary_wide(
        from_="2025-11-01 00:00:00",
        to="2025-11-01 01:00:00",
        variables=["state"],
        scope_type="heating",
        scope_id="main",
        bin_="hour",
        metric="sum_value",
        decimal_places=3,
    )

    print_rows("loaded availability rows", loaded, limit=10)
    print_rows("heating.main state hourly summary", summary)
    print_rows("heating.main state hourly wide sum", wide)


if __name__ == "__main__":
    main()
