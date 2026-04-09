import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from flask_app import app as flask_app_module


class CaptionFrameApiTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()

    def test_caption_frame_requires_prompt(self):
        resp = self.client.post("/api/caption_frame", json={})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("error"), "prompt is required")

    def test_caption_frame_requires_io_id(self):
        resp = self.client.post("/api/caption_frame", json={"prompt": "describe scene"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("error"), "io_id is required")

    @patch.object(flask_app_module, "_get_device_preview_frame_bytes", return_value=None)
    @patch.object(flask_app_module.io_manager, "get_stream_info", return_value={"name": "Front Door", "source": "network"})
    def test_caption_frame_returns_404_when_no_frame(self, _mock_stream, _mock_preview):
        resp = self.client.post("/api/caption_frame", json={"io_id": "net0", "prompt": "what is visible?"})
        self.assertEqual(resp.status_code, 404)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("error"), "No frame available for this device")
        self.assertEqual(data.get("io_id"), "net0")

    @patch.object(flask_app_module, "_get_device_preview_frame_bytes", return_value=b"jpeg-bytes")
    @patch.object(flask_app_module.model_provider, "_sync_generate_content", return_value=SimpleNamespace(analysis="A person in frame"))
    def test_caption_frame_success(self, _mock_generate, _mock_preview):
        resp = self.client.post("/api/caption_frame", json={"io_id": "net0", "prompt": "describe scene"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("io_id"), "net0")
        self.assertEqual(data.get("analysis"), "A person in frame")

    @patch.object(flask_app_module, "_get_device_preview_frame_bytes", return_value=b"jpeg-bytes")
    @patch.object(flask_app_module.model_provider, "_sync_generate_content", side_effect=RuntimeError("provider failed"))
    def test_caption_frame_provider_error(self, _mock_generate, _mock_preview):
        resp = self.client.post("/api/caption_frame", json={"io_id": "net0", "prompt": "describe scene"})
        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertIn("provider failed", data.get("error", ""))

    @patch.object(flask_app_module, "_get_device_preview_frame_bytes", return_value=b"jpeg-bytes")
    def test_caption_frame_local_vllm_connect_error_returns_actionable_hint(self, _mock_preview):
        class LocalVLLMProvider:
            def _sync_generate_content(self, image_base64, prompt, response_model, usage_context=None):
                raise httpx.ConnectError("Connection refused")

        original_provider = flask_app_module.task_manager._model_provider
        try:
            flask_app_module.task_manager._model_provider = LocalVLLMProvider()
            with patch.dict("os.environ", {"VIDEO_INGESTOR_MODEL": "local-vllm"}, clear=False):
                resp = self.client.post("/api/caption_frame", json={"io_id": "net0", "prompt": "describe scene"})
        finally:
            flask_app_module.task_manager._model_provider = original_provider

        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("current_model"), "local-vllm")
        self.assertEqual(data.get("model_provider"), "LocalVLLMProvider")
        self.assertIn("not reachable", data.get("error", ""))
        self.assertIn("VIDEO_INGESTOR_MODEL", data.get("hint", ""))

    @patch.object(flask_app_module, "_get_device_preview_frame_bytes", return_value=b"jpeg-bytes")
    def test_caption_frame_invalid_api_key_returns_actionable_hint(self, _mock_preview):
        class AnthropicProvider:
            def _sync_generate_content(self, image_base64, prompt, response_model, usage_context=None):
                raise RuntimeError(
                    "Error code: 401 - {'type': 'error', 'error': {'type': 'authentication_error', "
                    "'message': 'invalid x-api-key'}}"
                )

        original_provider = flask_app_module.task_manager._model_provider
        try:
            flask_app_module.task_manager._model_provider = AnthropicProvider()
            with patch.dict("os.environ", {"VIDEO_INGESTOR_MODEL": "claude-sonnet-4-6"}, clear=False):
                resp = self.client.post("/api/caption_frame", json={"io_id": "net0", "prompt": "describe scene"})
        finally:
            flask_app_module.task_manager._model_provider = original_provider

        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertEqual(data.get("current_model"), "claude-sonnet-4-6")
        self.assertEqual(data.get("required_setting"), "ANTHROPIC_API_KEY")
        self.assertIn("valid ANTHROPIC_API_KEY", data.get("error", ""))
        self.assertIn("Save a valid ANTHROPIC_API_KEY", data.get("hint", ""))


if __name__ == "__main__":
    unittest.main()
