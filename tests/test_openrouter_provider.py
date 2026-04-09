"""Tests for OpenRouter provider behavior."""

import unittest
from unittest.mock import Mock, patch

from pydantic import BaseModel

from videomemory.system.model_providers.openrouter_provider import (
    OpenRouterCustomModelProvider,
    OpenRouterQwen3VL8BProvider,
)


class _OutputModel(BaseModel):
    analysis: str


class OpenRouterProviderTests(unittest.TestCase):
    def test_openrouter_custom_provider_marks_itself_initialized(self):
        provider = OpenRouterCustomModelProvider(
            model_name="qwen/qwen3.5-flash-02-23",
            api_key="test-openrouter-key",
        )

        self.assertIsNotNone(provider._client)
        self.assertEqual(provider._model_name, "qwen/qwen3.5-flash-02-23")

    @patch("videomemory.system.model_providers.openrouter_provider.httpx.Client")
    def test_openrouter_provider_salvages_single_text_field_under_wrong_key(self, mock_client_cls):
        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": {
                            "description": "A blue circle, a green square, and an orange triangle."
                        }
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 105,
                "completion_tokens": 35,
                "total_tokens": 140,
            },
        }
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client_cls.return_value.__exit__.return_value = False

        provider = OpenRouterQwen3VL8BProvider(api_key="test-openrouter-key")
        result = provider._sync_generate_content(
            image_base64="ZmFrZQ==",
            prompt="Describe the image",
            response_model=_OutputModel,
        )

        self.assertEqual(result.analysis, "A blue circle, a green square, and an orange triangle.")

    @patch("videomemory.system.model_providers.openrouter_provider.httpx.Client")
    def test_openrouter_provider_salvages_single_text_field_from_json_string(self, mock_client_cls):
        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"description":"A blue circle, a green square, and an orange triangle."}'
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 105,
                "completion_tokens": 35,
                "total_tokens": 140,
            },
        }
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client_cls.return_value.__exit__.return_value = False

        provider = OpenRouterQwen3VL8BProvider(api_key="test-openrouter-key")
        result = provider._sync_generate_content(
            image_base64="ZmFrZQ==",
            prompt="Describe the image",
            response_model=_OutputModel,
        )

        self.assertEqual(result.analysis, "A blue circle, a green square, and an orange triangle.")
