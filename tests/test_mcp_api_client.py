import unittest
from unittest.mock import Mock

from videomemory.mcp_server import ApiError, VideoMemoryApiClient


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = "" if payload is None else "json"

    def json(self):
        return self._payload


class McpApiClientTests(unittest.TestCase):
    def test_analyze_feed_calls_caption_frame_endpoint(self):
        client = VideoMemoryApiClient(base_url="http://localhost:5050")
        session = Mock()
        session.request.return_value = _Resp(200, {"status": "success", "analysis": "ok"})
        client.session = session

        result = client.analyze_feed(io_id="net0", prompt="describe")

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(session.request.call_count, 1)
        _, kwargs = session.request.call_args
        self.assertEqual(kwargs["method"], "POST")
        self.assertTrue(kwargs["url"].endswith("/api/caption_frame"))
        self.assertEqual(kwargs["json"], {"io_id": "net0", "prompt": "describe"})

    def test_analyze_feed_falls_back_to_legacy_endpoint(self):
        client = VideoMemoryApiClient(base_url="http://localhost:5050")
        session = Mock()
        session.request.side_effect = [
            _Resp(404, {"raw_text": "<!doctype html><title>404 Not Found</title>"}),
            _Resp(200, {"status": "success", "analysis": "legacy-ok"}),
        ]
        client.session = session

        result = client.analyze_feed(io_id="net0", prompt="describe")

        self.assertEqual(result.get("analysis"), "legacy-ok")
        self.assertEqual(session.request.call_count, 2)

        first_call = session.request.call_args_list[0].kwargs
        second_call = session.request.call_args_list[1].kwargs

        self.assertTrue(first_call["url"].endswith("/api/caption_frame"))
        self.assertTrue(second_call["url"].endswith("/api/device/net0/analyze"))

    def test_analyze_feed_does_not_fallback_on_caption_api_error(self):
        client = VideoMemoryApiClient(base_url="http://localhost:5050")
        session = Mock()
        session.request.return_value = _Resp(404, {"status": "error", "error": "No frame available for this device"})
        client.session = session

        with self.assertRaises(ApiError) as ctx:
            client.analyze_feed(io_id="net0", prompt="describe")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(session.request.call_count, 1)
        _, kwargs = session.request.call_args
        self.assertTrue(kwargs["url"].endswith("/api/caption_frame"))


if __name__ == "__main__":
    unittest.main()
