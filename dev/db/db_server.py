import json
import os
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db_queries


HOST = os.environ.get("DB_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("DB_API_PORT", "8765"))


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def json_bytes(payload):
    return json.dumps(
        payload,
        default=json_default,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def get_param(params, name):
    if name in params:
        return params[name]

    if name == "from_" and "from" in params:
        return params["from"]

    return None


def one(params, name, default=None):
    values = get_param(params, name)
    if not values:
        return default

    if isinstance(values, list):
        return values[-1]

    return values


def required(params, name):
    value = one(params, name)
    if value in (None, ""):
        raise ValueError(f"missing required query parameter: {name}")

    return value


def variables(params):
    values = get_param(params, "variables")
    if values is None:
        values = []
    elif isinstance(values, str):
        values = [values]
    elif not isinstance(values, list):
        values = list(values)

    parsed = []

    for value in values:
        parsed.extend(part.strip() for part in value.split(",") if part.strip())

    if not parsed:
        raise ValueError("missing required query parameter: variables")

    return parsed


def decimal_places(params):
    value = one(params, "decimal_places", "1")

    try:
        return int(value)
    except ValueError as error:
        raise ValueError("decimal_places must be an integer") from error


def query_args(params):
    return {
        "from_": required(params, "from_"),
        "to": required(params, "to"),
        "variables": variables(params),
        "scope_type": required(params, "scope_type"),
        "scope_id": one(params, "scope_id"),
    }


def api_index():
    return {
        "endpoints": {
            "/api/health": "server health",
            "/api/streams": "stream catalog",
            "/api/availability": "stream first/last/count availability",
            "/api/query": "raw observations; add shape=grouped for binned raw groups",
            "/api/summary": "binned summaries; add shape=wide for pivoted output",
        },
        "query_parameters": {
            "from": "inclusive start timestamp, e.g. 2025-11-01 00:00:00",
            "to": "exclusive end timestamp",
            "scope_type": "required for query and summary",
            "scope_id": "optional scope id",
            "variables": "comma-separated or repeated variable names",
            "bin": "hour or day; default hour for grouped/summary",
            "decimal_places": "0-6; default 1 for summaries",
            "metric": "wide summary metric, e.g. mean_value or sum_value",
        },
    }


class DbRequestHandler(BaseHTTPRequestHandler):
    server_version = "KazanfutesDbServer/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        self.respond(parsed.path, parse_qs(parsed.query))

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"

        try:
            params = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as error:
            self.write_json(400, {"error": f"invalid JSON body: {error}"})
            return

        if not isinstance(params, dict):
            self.write_json(400, {"error": "JSON body must be an object"})
            return

        self.respond(parsed.path, params)

    def respond(self, path, params):
        try:
            status = 200
            payload = self.route(path, params)
        except ValueError as error:
            status = 400
            payload = {"error": str(error)}
        except Exception as error:
            status = 500
            payload = {"error": f"{type(error).__name__}: {error}"}

        self.write_json(status, payload)

    def write_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_, *args):
        print(f"{self.log_date_time_string()} {self.address_string()} {format_ % args}")

    def route(self, path, params):
        if path in ("", "/"):
            return api_index()

        if path == "/api/health":
            return {"ok": True}

        if path == "/api/streams":
            return {"rows": db_queries.get_streams()}

        if path == "/api/availability":
            return {"rows": db_queries.get_stream_availability()}

        if path == "/api/query":
            args = query_args(params)
            shape = one(params, "shape", "raw")

            if shape == "raw":
                return {"rows": db_queries.query_observations(**args)}

            if shape == "grouped":
                return {
                    "rows": db_queries.query_observations_grouped(
                        **args,
                        bin_=one(params, "bin", "hour"),
                    )
                }

            raise ValueError("shape must be one of: raw, grouped")

        if path == "/api/summary":
            args = query_args(params)
            shape = one(params, "shape", "long")
            bin_ = one(params, "bin", "hour")
            places = decimal_places(params)

            if shape == "long":
                return {
                    "rows": db_queries.query_summary(
                        **args,
                        bin_=bin_,
                        decimal_places=places,
                    )
                }

            if shape == "wide":
                return {
                    "rows": db_queries.query_summary_wide(
                        **args,
                        bin_=bin_,
                        metric=one(params, "metric", "mean_value"),
                        decimal_places=places,
                    )
                }

            raise ValueError("shape must be one of: long, wide")

        raise ValueError(f"unknown endpoint: {path}")


def run():
    server = ThreadingHTTPServer((HOST, PORT), DbRequestHandler)
    print(f"serving read-only db API on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
