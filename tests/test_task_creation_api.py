import os
import unittest
from unittest.mock import MagicMock, patch

import flask_app.app as app_module


class TaskCreationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_create_task_rejects_missing_selected_model_key(self):
        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module.videomemory.tools.tasks, "add_task") as mock_add_task,
            patch.dict(os.environ, {"VIDEO_INGESTOR_MODEL": "claude-sonnet-4-6"}, clear=False),
        ):
            resp = self.client.post(
                "/api/tasks",
                json={"io_id": "net0", "task_description": "Watch for a person entering the room"},
            )

        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "error")
        self.assertEqual(body.get("current_model"), "claude-sonnet-4-6")
        self.assertEqual(body.get("required_setting"), "ANTHROPIC_API_KEY")
        self.assertEqual(body.get("settings_url"), "/settings")
        self.assertIn("Open the Settings tab", body.get("hint", ""))
        mock_add_task.assert_not_called()

    def test_create_task_allows_configured_selected_model_key(self):
        mock_db = MagicMock()

        def get_setting(key):
            if key == "ANTHROPIC_API_KEY":
                return "sk-ant-test"
            return None

        mock_db.get_setting.side_effect = get_setting
        add_result = {
            "status": "success",
            "task_id": "0",
            "io_id": "net0",
            "task_description": "Watch for a person entering the room",
        }

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module.videomemory.tools.tasks, "add_task", return_value=add_result) as mock_add_task,
            patch.dict(os.environ, {"VIDEO_INGESTOR_MODEL": "claude-sonnet-4-6"}, clear=False),
        ):
            resp = self.client.post(
                "/api/tasks",
                json={"io_id": "net0", "task_description": "Watch for a person entering the room"},
            )

        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "success")
        self.assertEqual(body.get("task_id"), "0")
        mock_add_task.assert_called_once_with(
            "net0",
            "Watch for a person entering the room",
            bot_id=None,
            save_note_frames=None,
            save_note_videos=None,
        )

    def test_create_task_passes_per_task_evidence_preferences(self):
        mock_db = MagicMock()
        add_result = {
            "status": "success",
            "task_id": "0",
            "io_id": "net0",
            "task_description": "Watch for a person entering the room",
            "save_note_frames": False,
            "save_note_videos": True,
        }

        with (
            patch.object(app_module, "db", mock_db),
            patch.object(app_module, "_build_task_creation_model_error", return_value=None),
            patch.object(app_module.videomemory.tools.tasks, "add_task", return_value=add_result) as mock_add_task,
        ):
            resp = self.client.post(
                "/api/tasks",
                json={
                    "io_id": "net0",
                    "task_description": "Watch for a person entering the room",
                    "save_note_frames": False,
                    "save_note_videos": True,
                },
            )

        self.assertEqual(resp.status_code, 201)
        mock_add_task.assert_called_once_with(
            "net0",
            "Watch for a person entering the room",
            bot_id=None,
            save_note_frames=False,
            save_note_videos=True,
        )


if __name__ == "__main__":
    unittest.main()
