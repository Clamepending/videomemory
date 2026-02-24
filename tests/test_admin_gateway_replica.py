import os
import unittest
from unittest.mock import patch

try:
    import flask  # noqa: F401
    HAS_FLASK = True
except Exception:
    HAS_FLASK = False


class _MockResp:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text if text else ("x" if data is not None else "")

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


@unittest.skipUnless(HAS_FLASK, "flask not installed in host test environment")
class AdminGatewayReplicaTests(unittest.TestCase):
    def setUp(self):
        os.environ["GATEWAY_HOOK_PATH"] = "videomemory-alert"
        os.environ["GATEWAY_TOKEN"] = "secret"
        os.environ["GATEWAY_FORWARD_TO_VIDEOMEMORY_CHAT"] = "1"
        os.environ["VIDEOMEMORY_BASE_URL"] = "http://videomemory:5050"
        os.environ.pop("VIDEOMEMORY_AGENT_SESSION_ID", None)

    def tearDown(self):
        for key in [
            "GATEWAY_HOOK_PATH",
            "GATEWAY_TOKEN",
            "GATEWAY_FORWARD_TO_VIDEOMEMORY_CHAT",
            "VIDEOMEMORY_BASE_URL",
            "VIDEOMEMORY_AGENT_SESSION_ID",
        ]:
            os.environ.pop(key, None)

    def _make_app(self):
        from admin_gateway_replica.app import create_app

        app = create_app()
        app.testing = True
        return app

    def test_rejects_missing_auth(self):
        app = self._make_app()
        client = app.test_client()
        resp = client.post("/hooks/videomemory-alert", json={"task_id": "1"})
        self.assertEqual(resp.status_code, 401)

    def test_rejects_non_object_json(self):
        app = self._make_app()
        client = app.test_client()
        resp = client.post(
            "/hooks/videomemory-alert",
            headers={"Authorization": "Bearer secret"},
            json=["not", "an", "object"],
        )
        self.assertEqual(resp.status_code, 400)

    @patch("admin_gateway_replica.app.requests.post")
    def test_forwards_hook_to_videomemory_chat(self, mock_post):
        mock_post.side_effect = [
            _MockResp(data={"session_id": "chat_abc"}),
            _MockResp(data={"response": "Agent handled alert"}),
        ]
        app = self._make_app()
        client = app.test_client()
        resp = client.post(
            "/hooks/videomemory-alert",
            headers={"Authorization": "Bearer secret"},
            json={"io_id": "net0", "task_id": "1", "note": "Package detected", "task_description": "Watch for package"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["forwarded"])
        self.assertEqual(data["session_id"], "chat_abc")
        self.assertIn("Package detected", data["message"])
        self.assertEqual(mock_post.call_count, 2)

    @patch("admin_gateway_replica.app.requests.post")
    def test_reuses_existing_session_id(self, mock_post):
        os.environ["VIDEOMEMORY_AGENT_SESSION_ID"] = "chat_fixed"
        mock_post.side_effect = [_MockResp(data={"response": "ok"})]
        app = self._make_app()
        client = app.test_client()
        resp = client.post(
            "/hooks/videomemory-alert",
            headers={"Authorization": "Bearer secret"},
            json={"io_id": "net0", "task_id": "1", "note": "Person detected", "task_description": "Watch"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
