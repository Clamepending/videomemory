import os
import unittest
from unittest.mock import MagicMock, patch

import flask_app.app as app_module


class SettingsRuntimeReloadTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_model_key_save_triggers_runtime_reload(self):
        mock_db = MagicMock()
        mock_task_manager = MagicMock()
        mock_task_manager.reload_model_provider.return_value = {
            "provider": "Gemini25FlashProvider",
            "updated_ingestors": 1,
        }

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module, "task_manager", mock_task_manager),
            patch.dict(os.environ, {"VIDEO_INGESTOR_MODEL": "gemini-2.5-flash-lite"}, clear=False),
        ):
            resp = self.client.put(
                "/api/settings/GOOGLE_API_KEY",
                json={"value": "AIza-test-key"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "saved", "key": "GOOGLE_API_KEY"})
        mock_db.set_setting.assert_called_once_with("GOOGLE_API_KEY", "AIza-test-key")
        mock_task_manager.reload_model_provider.assert_called_once_with(model_name="gemini-2.5-flash-lite")

    def test_model_key_clear_triggers_runtime_reload(self):
        mock_db = MagicMock()
        mock_task_manager = MagicMock()
        mock_task_manager.reload_model_provider.return_value = {
            "provider": "Gemini25FlashProvider",
            "updated_ingestors": 0,
        }

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module, "task_manager", mock_task_manager),
            patch("dotenv.dotenv_values", return_value={}),
            patch.dict(os.environ, {"VIDEO_INGESTOR_MODEL": ""}, clear=False),
        ):
            resp = self.client.put(
                "/api/settings/GOOGLE_API_KEY",
                json={"value": ""},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "cleared", "key": "GOOGLE_API_KEY"})
        mock_db.delete_setting.assert_called_once_with("GOOGLE_API_KEY")
        mock_task_manager.reload_model_provider.assert_called_once_with(model_name=None)

    def test_model_selection_save_triggers_runtime_reload_with_new_model(self):
        mock_db = MagicMock()
        mock_task_manager = MagicMock()

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module, "task_manager", mock_task_manager),
            patch.dict(os.environ, {"VIDEO_INGESTOR_MODEL": "gemini-2.5-flash"}, clear=False),
        ):
            resp = self.client.put(
                "/api/settings/VIDEO_INGESTOR_MODEL",
                json={"value": "gpt-4o-mini"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "saved", "key": "VIDEO_INGESTOR_MODEL"})
        mock_db.set_setting.assert_called_once_with("VIDEO_INGESTOR_MODEL", "gpt-4o-mini")
        mock_task_manager.reload_model_provider.assert_called_once_with(model_name="gpt-4o-mini")

    def test_model_reload_failure_returns_500_but_still_persists_setting(self):
        mock_db = MagicMock()
        mock_task_manager = MagicMock()
        mock_task_manager.reload_model_provider.side_effect = RuntimeError("reload failed")

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module, "task_manager", mock_task_manager),
            patch.dict(os.environ, {"VIDEO_INGESTOR_MODEL": "gemini-2.5-flash"}, clear=False),
        ):
            resp = self.client.put(
                "/api/settings/GOOGLE_API_KEY",
                json={"value": "AIza-test-key"},
            )

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertIn("error", body)
        mock_db.set_setting.assert_called_once_with("GOOGLE_API_KEY", "AIza-test-key")
        mock_task_manager.reload_model_provider.assert_called_once_with(model_name="gemini-2.5-flash")

    def test_openclaw_key_triggers_notifier_reload_without_model_reload(self):
        mock_db = MagicMock()
        mock_task_manager = MagicMock()

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module, "task_manager", mock_task_manager),
            patch.object(app_module, "_reload_openclaw_notifier_from_env") as mock_notifier_reload,
        ):
            resp = self.client.put(
                "/api/settings/VIDEOMEMORY_OPENCLAW_WEBHOOK_URL",
                json={"value": "https://openclaw.example/hook"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "saved", "key": "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL"})
        mock_db.set_setting.assert_called_once_with(
            "VIDEOMEMORY_OPENCLAW_WEBHOOK_URL",
            "https://openclaw.example/hook",
        )
        mock_notifier_reload.assert_called_once()
        mock_task_manager.reload_model_provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
