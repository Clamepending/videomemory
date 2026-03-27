"""Tests for OpenRouter provider initialization behavior."""

import unittest

from videomemory.system.model_providers.openrouter_provider import OpenRouterCustomModelProvider


class OpenRouterProviderTests(unittest.TestCase):
    def test_openrouter_custom_provider_marks_itself_initialized(self):
        provider = OpenRouterCustomModelProvider(
            model_name="qwen/qwen3.5-flash-02-23",
            api_key="test-openrouter-key",
        )

        self.assertIsNotNone(provider._client)
        self.assertEqual(provider._model_name, "qwen/qwen3.5-flash-02-23")
