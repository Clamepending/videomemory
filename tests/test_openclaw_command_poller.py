import unittest
from unittest.mock import patch
import os

from videomemory.integrations.openclaw_command_poller import OpenClawCommandPoller


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class OpenClawCommandPollerTests(unittest.TestCase):
    def test_is_disabled_in_streaming_mode(self):
        with patch.dict(os.environ, {"VIDEOMEMORY_DEPLOYMENT_MODE": "streaming"}, clear=False):
            poller = OpenClawCommandPoller(pull_url="https://example.test/pull", enabled=True)
            self.assertFalse(poller.is_enabled())

    def test_map_create_task_action(self):
        with patch.dict(os.environ, {"VIDEOMEMORY_DEPLOYMENT_MODE": "event"}, clear=False):
            poller = OpenClawCommandPoller(pull_url="https://example.test/pull", enabled=True)
        method, path, body, query = poller._map_action(
            "create_task",
            {"io_id": "cam1", "task_description": "Watch door"},
        )
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/tasks")
        self.assertEqual(body["io_id"], "cam1")
        self.assertEqual(body["task_description"], "Watch door")
        self.assertIsNone(query)

    def test_handle_command_returns_error_for_unknown_action(self):
        with patch.dict(os.environ, {"VIDEOMEMORY_DEPLOYMENT_MODE": "event"}, clear=False):
            poller = OpenClawCommandPoller(pull_url="https://example.test/pull", enabled=True)
            result = poller._handle_command({"request_id": "r1", "action": "nope", "args": {}})
        self.assertEqual(result["request_id"], "r1")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported action", result["error"])

    @patch("videomemory.integrations.openclaw_command_poller.requests.post")
    @patch("videomemory.integrations.openclaw_command_poller.requests.request")
    def test_poll_once_pulls_executes_and_posts_result(self, mock_request, mock_post):
        # First POST: pull commands. Second POST: command result callback.
        mock_post.side_effect = [
            FakeResponse(
                status_code=200,
                json_data={
                    "commands": [
                        {
                            "request_id": "cmd1",
                            "action": "list_devices",
                            "args": {},
                        }
                    ]
                },
            ),
            FakeResponse(status_code=200, json_data={"ok": True}),
        ]
        mock_request.return_value = FakeResponse(
            status_code=200,
            json_data={"devices": {"camera": [{"io_id": "0", "name": "Cam"}]}},
        )

        with patch.dict(os.environ, {"VIDEOMEMORY_DEPLOYMENT_MODE": "event"}, clear=False):
            poller = OpenClawCommandPoller(
                pull_url="https://cloud.example/pull",
                result_url="https://cloud.example/result",
                bearer_token="secret",
                edge_id="edge-1",
                local_api_base_url="http://127.0.0.1:5050",
                enabled=True,
            )
            processed = poller.poll_once()

        self.assertEqual(processed, 1)
        mock_request.assert_called_once()
        # Validate local API request mapping.
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["url"], "http://127.0.0.1:5050/api/devices")

        # Validate result callback payload includes request_id + edge_id.
        self.assertEqual(mock_post.call_count, 2)
        _, result_kwargs = mock_post.call_args
        self.assertEqual(result_kwargs["json"]["request_id"], "cmd1")
        self.assertEqual(result_kwargs["json"]["edge_id"], "edge-1")
        self.assertEqual(result_kwargs["json"]["status"], "success")

    @patch("videomemory.integrations.openclaw_command_poller.requests.post")
    def test_pull_response_single_command_object_supported(self, mock_post):
        mock_post.return_value = FakeResponse(
            status_code=200,
            json_data={"request_id": "cmd2", "action": "health"},
        )
        with patch.dict(os.environ, {"VIDEOMEMORY_DEPLOYMENT_MODE": "event"}, clear=False):
            poller = OpenClawCommandPoller(pull_url="https://cloud.example/pull", enabled=True)
            commands = poller._pull_commands()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["request_id"], "cmd2")


if __name__ == "__main__":
    unittest.main()
