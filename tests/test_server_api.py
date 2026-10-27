import io
import json
import unittest
from unittest.mock import patch

import server


class FakeHandler(server.DashboardHandler):
    def __init__(self, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.path = "/api/update"
        self.headers = {"Content-Length": str(len(encoded))}
        self.rfile = io.BytesIO(encoded)
        self.result = None

    def send_json(self, payload, status=200):
        self.result = (status, payload)


class UpdateApiTests(unittest.TestCase):
    def call(self, payload):
        handler = FakeHandler(payload)
        handler.do_POST()
        return handler.result

    def test_invalid_range_is_400_without_writing(self):
        with patch.object(server, "write_rows") as write:
            status, body = self.call({"start": "bad", "end": "2026-10"})
        self.assertEqual(status, 400)
        self.assertIn("月份格式", body["error"])
        write.assert_not_called()

    def test_data_source_failure_is_502_without_writing(self):
        with patch.object(server, "update_monthly_data", side_effect=server.DataUpdateError("AkShare unavailable")), patch.object(server, "write_rows") as write:
            status, body = self.call({"start": "2026-10", "end": "2026-10"})
        self.assertEqual(status, 502)
        self.assertIn("AkShare unavailable", body["error"])
        write.assert_not_called()

    def test_complete_update_is_written_and_summarized(self):
        result = {
            "rows": [{"month": "2026-10", "values": [1.0, 2.0, 3.0, 4.0], "hsi": 25000.0, "note": ""}],
            "months": 1,
            "sources": {"hkma_m2": "ok", "ppi": "ok", "retail": "ok", "credit": "ok", "hsi": "ok"},
        }
        with patch.object(server, "update_monthly_data", return_value=result), patch.object(server, "write_rows") as write:
            status, body = self.call({"start": "2026-10", "end": "2026-10"})
        self.assertEqual(status, 200)
        self.assertEqual(body["written"], 1)
        self.assertEqual(body["sources"]["hsi"], "ok")
        write.assert_called_once_with(result["rows"])


if __name__ == "__main__":
    unittest.main()
