import unittest
from unittest.mock import patch

from flask_app import app as flask_app_module


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = "" if payload is None else "json"

    def json(self):
        return self._payload


class McpEventsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()

    @patch.object(flask_app_module.requests, "get")
    def test_get_mcp_events_proxies_success(self, mock_get):
        mock_get.return_value = _Resp(200, {"status": "ok", "count": 1, "events": [{"seq": 1}]})

        resp = self.client.get("/api/mcp/events?limit=50")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("count"), 1)
        self.assertEqual(data.get("events")[0]["seq"], 1)

    def test_get_mcp_events_rejects_bad_limit(self):
        resp = self.client.get("/api/mcp/events?limit=abc")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")

    @patch.object(flask_app_module.requests, "delete")
    def test_clear_mcp_events_proxies_success(self, mock_delete):
        mock_delete.return_value = _Resp(200, {"status": "ok", "cleared": 5})

        resp = self.client.delete("/api/mcp/events")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("cleared"), 5)


if __name__ == "__main__":
    unittest.main()
