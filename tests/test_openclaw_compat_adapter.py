import unittest
from unittest.mock import patch
import os

from videomemory.openclaw_compat_adapter import create_app


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class OpenClawCompatAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {
                "OPENCLAW_COMPAT_TARGETS": "http://openclaw:18789/hooks/videomemory-alert,http://openclaw:18789/webhooks/videomemory-alert",
                "OPENCLAW_COMPAT_TARGET_TOKEN": "hook-token",
            },
            clear=False,
        )
        self.env_patch.start()
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self.env_patch.stop()

    @patch("videomemory.openclaw_compat_adapter.requests.post")
    def test_forward_success_on_first_target(self, mock_post):
        mock_post.return_value = FakeResponse(status_code=200, text="ok")
        r = self.client.post(
            "/videomemory-alert",
            json={"event_type": "task_update", "edge_id": "edge1", "task_id": "1", "note": "x"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "forwarded")
        self.assertIn("target", body)

    @patch("videomemory.openclaw_compat_adapter.requests.post")
    def test_accepts_when_all_targets_fail(self, mock_post):
        mock_post.side_effect = [
            FakeResponse(status_code=405, text="Method Not Allowed"),
            FakeResponse(status_code=404, text="Not Found"),
        ]
        r = self.client.post(
            "/videomemory-alert",
            json={"event_type": "task_update", "edge_id": "edge1", "task_id": "1", "note": "x"},
        )
        self.assertEqual(r.status_code, 202)
        body = r.get_json()
        self.assertEqual(body["status"], "accepted_unforwarded")
        self.assertEqual(len(body["attempts"]), 2)

    @patch("videomemory.openclaw_compat_adapter.requests.post")
    def test_recent_endpoint(self, mock_post):
        mock_post.return_value = FakeResponse(status_code=200, text="ok")
        self.client.post("/videomemory-alert", json={"event_type": "task_update", "edge_id": "edge1"})
        r = self.client.get("/recent?limit=5")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertGreaterEqual(len(data["items"]), 1)


if __name__ == "__main__":
    unittest.main()
