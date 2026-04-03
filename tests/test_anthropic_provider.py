import os
import unittest
from unittest.mock import Mock, patch

from pydantic import BaseModel

from videomemory.system.model_providers.anthropic_provider import AnthropicClaudeSonnet46Provider
from videomemory.system.model_providers.factory import get_VLM_provider


class _OutputModel(BaseModel):
    answer: str


class AnthropicProviderTests(unittest.TestCase):
    @patch("videomemory.system.model_providers.anthropic_provider.Anthropic")
    def test_provider_parses_structured_output(self, mock_anthropic):
        mock_client = Mock()
        mock_client.messages.parse.return_value = Mock(parsed_output={"answer": "red marker visible"})
        mock_anthropic.return_value = mock_client

        original = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "test-ant-key"
        try:
            provider = AnthropicClaudeSonnet46Provider()
            result = provider._sync_generate_content("ZmFrZQ==", "Look for a red marker", _OutputModel)
        finally:
            if original is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = original

        self.assertEqual(result.answer, "red marker visible")
        mock_client.messages.parse.assert_called_once()
        call = mock_client.messages.parse.call_args
        self.assertEqual(call.kwargs["model"], "claude-sonnet-4-6")
        self.assertEqual(call.kwargs["output_format"], _OutputModel)

    def test_factory_returns_anthropic_provider(self):
        provider = get_VLM_provider("claude-sonnet-4-6")
        self.assertIsInstance(provider, AnthropicClaudeSonnet46Provider)


if __name__ == "__main__":
    unittest.main()
