#!/usr/bin/env python3
"""Small CSV-backed web server for the Hong Kong leading indicator dashboard."""

import argparse
import csv
import json
import os
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from macro_data import DataUpdateError, parse_month_range, update_monthly_data


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_PATH = Path(os.environ.get("HK_INDICATOR_CSV", str(PROJECT_ROOT / "data" / "data.csv")))
FIELDS = ("month", "m2", "ppi", "retail", "credit", "hsi", "note")
NUMBER_FIELDS = {"m2", "ppi", "retail", "credit", "hsi"}


def parse_number(value):
    if value in (None, ""):
        return None
    return float(value)


def read_rows():
    with DATA_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for item in reader:
            rows.append({
                "month": item.get("month", ""),
                "values": [parse_number(item.get(name, "")) for name in ("m2", "ppi", "retail", "credit")],
                "hsi": parse_number(item.get("hsi", "")),
                "note": item.get("note", ""),
            })
        return rows


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def write_rows(rows):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".data-", suffix=".csv", dir=str(DATA_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for row in rows:
                values = row.get("values") or []
                writer.writerow({
                    "month": str(row.get("month", "")),
                    "m2": csv_value(values[0] if len(values) > 0 else None),
                    "ppi": csv_value(values[1] if len(values) > 1 else None),
                    "retail": csv_value(values[2] if len(values) > 2 else None),
                    "credit": csv_value(values[3] if len(values) > 3 else None),
                    "hsi": csv_value(row.get("hsi")),
                    "note": str(row.get("note", "")),
                })
        os.replace(temporary, DATA_PATH)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def validate_rows(value):
    if not isinstance(value, list) or not value:
        raise ValueError("request body must be a non-empty array")
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("month"), str):
            raise ValueError("each row must include a month")
        values = row.get("values")
        if not isinstance(values, list) or len(values) != 4:
            raise ValueError("each row must include four indicator values")
        for number in values + [row.get("hsi")]:
            if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float))):
                raise ValueError("numeric fields must be numbers or null")


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/data":
            try:
                self.send_json(read_rows())
            except Exception as error:
                self.send_json({"error": str(error)}, 500)
            return
        if path == "/data/data.csv":
            try:
                body = DATA_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(404, "data.csv not found")
            return
        super().do_GET()

    def do_PUT(self):
        if urlparse(self.path).path != "/api/data":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            validate_rows(value)
            write_rows(value)
            self.send_json({"ok": True, "path": str(DATA_PATH)})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except Exception as error:
            self.send_json({"error": str(error)}, 500)

    def do_POST(self):
        if urlparse(self.path).path != "/api/update":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            start, end = parse_month_range(payload.get("start"), payload.get("end"))
            result = update_monthly_data(start, end)
            write_rows(result["rows"])
            self.send_json({
                "ok": True,
                "start": start,
                "end": end,
                "months": result["months"],
                "written": len(result["rows"]),
                "incomplete_months": result.get("incomplete_months", 0),
                "sources": result["sources"],
            })
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)
        except DataUpdateError as error:
            self.send_json({"error": str(error)}, 502)
        except Exception as error:
            self.send_json({"error": str(error)}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4174)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print("Dashboard running at http://%s:%s" % (args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
