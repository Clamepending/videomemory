import unittest
from unittest.mock import Mock, patch

from videomemory.system.task_manager import TaskManager


class TaskManagerRuntimeReloadTests(unittest.TestCase):
    @patch("videomemory.system.task_manager.get_VLM_provider")
    def test_reload_model_provider_updates_active_ingestors(self, mock_get_provider):
        old_provider = object()
        new_provider = object()
        mock_get_provider.return_value = new_provider

        manager = TaskManager(io_manager=None, model_provider=old_provider, db=None)
        ingestor_a = Mock()
        ingestor_b = Mock()
        manager._ingestors = {"0": ingestor_a, "1": ingestor_b}

        result = manager.reload_model_provider(model_name="gpt-4o-mini")

        self.assertIs(manager._model_provider, new_provider)
        mock_get_provider.assert_called_once_with(model_name="gpt-4o-mini")
        ingestor_a.set_model_provider.assert_called_once_with(new_provider)
        ingestor_b.set_model_provider.assert_called_once_with(new_provider)
        self.assertEqual(result["updated_ingestors"], 2)
        self.assertEqual(result["provider"], "object")


if __name__ == "__main__":
    unittest.main()
