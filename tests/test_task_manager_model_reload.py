import unittest
from unittest.mock import patch

from videomemory.system.model_providers.base import BaseModelProvider
from videomemory.system.task_manager import TaskManager


class _DummyProvider(BaseModelProvider):
    def _sync_generate_content(self, image_base64, prompt, response_model):
        raise NotImplementedError


class _FakeIngestor:
    def __init__(self):
        self.last_provider = None

    def set_model_provider(self, provider):
        self.last_provider = provider


class _FailingIngestor:
    def set_model_provider(self, provider):
        raise RuntimeError("boom")

class _LegacyIngestor:
    pass


class TaskManagerModelReloadTests(unittest.TestCase):
    def test_reload_model_provider_updates_manager_and_active_ingestors(self):
        manager = TaskManager(io_manager=None, model_provider=_DummyProvider(api_key="initial"), db=None)
        ingestor_a = _FakeIngestor()
        ingestor_b = _FakeIngestor()
        manager._ingestors = {"0": ingestor_a, "1": ingestor_b}

        new_provider = _DummyProvider(api_key="updated")
        with patch("videomemory.system.task_manager.get_VLM_provider", return_value=new_provider):
            result = manager.reload_model_provider(model_name="gemini-2.5-flash")

        self.assertIs(manager._model_provider, new_provider)
        self.assertIs(ingestor_a.last_provider, new_provider)
        self.assertIs(ingestor_b.last_provider, new_provider)
        self.assertEqual(result["provider"], type(new_provider).__name__)
        self.assertEqual(result["updated_ingestors"], 2)

    def test_reload_model_provider_continues_when_an_ingestor_fails(self):
        manager = TaskManager(io_manager=None, model_provider=_DummyProvider(api_key="initial"), db=None)
        ingestor_ok = _FakeIngestor()
        ingestor_bad = _FailingIngestor()
        manager._ingestors = {"0": ingestor_ok, "1": ingestor_bad}

        new_provider = _DummyProvider(api_key="updated")
        with patch("videomemory.system.task_manager.get_VLM_provider", return_value=new_provider):
            result = manager.reload_model_provider()

        self.assertIs(manager._model_provider, new_provider)
        self.assertIs(ingestor_ok.last_provider, new_provider)
        self.assertEqual(result["updated_ingestors"], 1)
        self.assertEqual(result["failed_ingestors"], ["1"])

    def test_reload_model_provider_supports_legacy_ingestor_without_setter(self):
        manager = TaskManager(io_manager=None, model_provider=_DummyProvider(api_key="initial"), db=None)
        legacy = _LegacyIngestor()
        manager._ingestors = {"legacy": legacy}

        new_provider = _DummyProvider(api_key="updated")
        with patch("videomemory.system.task_manager.get_VLM_provider", return_value=new_provider):
            result = manager.reload_model_provider()

        self.assertIs(manager._model_provider, new_provider)
        self.assertIs(legacy._model_provider, new_provider)
        self.assertEqual(result["updated_ingestors"], 1)
        self.assertEqual(result["failed_ingestors"], [])


if __name__ == "__main__":
    unittest.main()
