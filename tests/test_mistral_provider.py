"""Tests for Mistral Small 3.1 provider (OpenRouter cloud)."""
import unittest

from videomemory.system.model_providers import get_VLM_provider
from videomemory.system.model_providers.openrouter_provider import OpenRouterMistralSmall31Provider


class MistralProviderTests(unittest.TestCase):
    def test_mistral_small_31_cloud_provider_from_factory(self):
        provider = get_VLM_provider("mistral-small-3.1")
        self.assertIsInstance(provider, OpenRouterMistralSmall31Provider)
        self.assertEqual(provider._model_name, "mistralai/mistral-small-3.1-24b-instruct")
