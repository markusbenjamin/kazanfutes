import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8765"
DATETIME_KEYS = {
    "timestamp",
    "bin_start",
    "bin_end",
    "first_observation",
    "last_observation",
}


class DbApiError(RuntimeError):
    pass


def parse_datetime(value):
    if not isinstance(value, str):
        return value

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def restore_types(value, key=None):
    if isinstance(value, list):
        return [restore_types(item) for item in value]

    if isinstance(value, dict):
        return {
            item_key: restore_types(item_value, item_key)
            for item_key, item_value in value.items()
        }

    if key in DATETIME_KEYS:
        return parse_datetime(value)

    return value


class DbApi:
    def __init__(self, base_url=DEFAULT_BASE_URL, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, path, payload=None):
        url = f"{self.base_url}{path}"

        if payload is None:
            request = Request(url, method="GET")
        else:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            body = error.read().decode("utf-8")
            try:
                payload = json.loads(body)
                message = payload.get("error", body)
            except json.JSONDecodeError:
                message = body

            raise DbApiError(f"HTTP {error.code}: {message}") from error
        except URLError as error:
            raise DbApiError(f"could not reach {url}: {error.reason}") from error

        try:
            return restore_types(json.loads(body))
        except json.JSONDecodeError as error:
            raise DbApiError(f"invalid JSON response from {url}: {error}") from error

    def health(self):
        return self.request("/api/health")

    def get_streams(self):
        return self.request("/api/streams")["rows"]

    def get_stream_availability(self):
        return self.request("/api/availability")["rows"]

    def query_observations(self, from_, to, variables, scope_type, scope_id=None):
        return self.request(
            "/api/query",
            {
                "shape": "raw",
                "from_": from_,
                "to": to,
                "variables": variables,
                "scope_type": scope_type,
                "scope_id": scope_id,
            },
        )["rows"]

    def query_observations_grouped(
        self,
        from_,
        to,
        variables,
        scope_type,
        scope_id=None,
        bin_="hour",
    ):
        return self.request(
            "/api/query",
            {
                "shape": "grouped",
                "from_": from_,
                "to": to,
                "variables": variables,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "bin": bin_,
            },
        )["rows"]

    def query_summary(
        self,
        from_,
        to,
        variables,
        scope_type,
        scope_id=None,
        bin_="hour",
        decimal_places=1,
    ):
        return self.request(
            "/api/summary",
            {
                "shape": "long",
                "from_": from_,
                "to": to,
                "variables": variables,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "bin": bin_,
                "decimal_places": decimal_places,
            },
        )["rows"]

    def query_summary_wide(
        self,
        from_,
        to,
        variables,
        scope_type,
        scope_id=None,
        bin_="hour",
        metric="mean_value",
        decimal_places=1,
    ):
        return self.request(
            "/api/summary",
            {
                "shape": "wide",
                "from_": from_,
                "to": to,
                "variables": variables,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "bin": bin_,
                "metric": metric,
                "decimal_places": decimal_places,
            },
        )["rows"]


default_client = DbApi()


def health():
    return default_client.health()


def get_streams():
    return default_client.get_streams()


def get_stream_availability():
    return default_client.get_stream_availability()


def query_observations(from_, to, variables, scope_type, scope_id=None):
    return default_client.query_observations(from_, to, variables, scope_type, scope_id)


def query_observations_grouped(
    from_,
    to,
    variables,
    scope_type,
    scope_id=None,
    bin_="hour",
):
    return default_client.query_observations_grouped(
        from_,
        to,
        variables,
        scope_type,
        scope_id,
        bin_,
    )


def query_summary(
    from_,
    to,
    variables,
    scope_type,
    scope_id=None,
    bin_="hour",
    decimal_places=1,
):
    return default_client.query_summary(
        from_,
        to,
        variables,
        scope_type,
        scope_id,
        bin_,
        decimal_places,
    )


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
    return default_client.query_summary_wide(
        from_,
        to,
        variables,
        scope_type,
        scope_id,
        bin_,
        metric,
        decimal_places,
    )
