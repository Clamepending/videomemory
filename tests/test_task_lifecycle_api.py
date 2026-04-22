import unittest
from unittest.mock import MagicMock, patch

import flask_app.app as app_module
from videomemory.system.task_manager import TaskManager
from videomemory.system.task_types import NoteEntry, STATUS_DONE, Task


class TaskLifecycleApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_stop_task_marks_done_without_deleting(self):
        task_manager = MagicMock()
        task_manager.stop_task.return_value = {
            "status": "success",
            "message": "Task 'abc 123' stopped successfully",
            "task_id": "abc 123",
        }

        with patch.object(app_module, "task_manager", task_manager):
            resp = self.client.post("/api/task/abc%20123/stop")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")
        task_manager.stop_task.assert_called_once_with("abc 123")
        task_manager.remove_task.assert_not_called()

    def test_stop_task_returns_404_when_missing(self):
        task_manager = MagicMock()
        task_manager.stop_task.return_value = {
            "status": "error",
            "message": "Task 'missing' not found",
        }

        with patch.object(app_module, "task_manager", task_manager):
            resp = self.client.post("/api/task/missing/stop")

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["status"], "error")

    def test_stop_task_returns_400_when_already_stopped(self):
        task_manager = MagicMock()
        task_manager.stop_task.return_value = {
            "status": "error",
            "message": "Task '1' is already stopped",
        }

        with patch.object(app_module, "task_manager", task_manager):
            resp = self.client.post("/api/task/1/stop")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["status"], "error")

    def test_delete_task_still_permanently_removes_task(self):
        task_manager = MagicMock()
        task_manager.remove_task.return_value = True

        with patch.object(app_module, "task_manager", task_manager):
            resp = self.client.delete("/api/task/1")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")
        task_manager.remove_task.assert_called_once_with("1")
        task_manager.stop_task.assert_not_called()

    def test_tasks_page_exposes_pause_and_delete_controls(self):
        resp = self.client.get("/tasks")

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("pause-task-btn", html)
        self.assertIn("stopTask(", html)
        self.assertIn("deleteTask(", html)
        self.assertIn("/stop", html)


class TaskManagerStopTaskTests(unittest.TestCase):
    def test_stop_task_preserves_task_and_notes_while_removing_ingestor_task(self):
        db = MagicMock()
        manager = TaskManager(io_manager=None, model_provider=object(), db=None)
        manager._db = db
        task = Task(
            task_id="42",
            task_number=0,
            task_desc="Watch for a phone",
            task_note=[NoteEntry("phone visible", timestamp=1_700_000_000.0)],
            done=False,
            io_id="0",
        )
        ingestor = MagicMock()
        manager._tasks = {"42": task}
        manager._ingestors = {"0": ingestor}

        result = manager.stop_task("42")

        self.assertEqual(result["status"], "success")
        self.assertIn("42", manager._tasks)
        self.assertEqual(manager._tasks["42"].task_note[0].content, "phone visible")
        self.assertTrue(manager._tasks["42"].done)
        self.assertEqual(manager._tasks["42"].status, STATUS_DONE)
        self.assertNotIn("0", manager._ingestors)
        ingestor.remove_task.assert_called_once_with("Watch for a phone")
        db.update_task_done.assert_called_once_with("42", True, status=STATUS_DONE)
        db.delete_task.assert_not_called()

    def test_stop_task_keeps_ingestor_when_other_active_tasks_remain(self):
        manager = TaskManager(io_manager=None, model_provider=object(), db=None)
        stopped_task = Task(
            task_id="42",
            task_number=0,
            task_desc="Watch for a phone",
            done=False,
            io_id="0",
        )
        active_task = Task(
            task_id="43",
            task_number=1,
            task_desc="Watch for a person",
            done=False,
            io_id="0",
        )
        ingestor = MagicMock()
        manager._tasks = {"42": stopped_task, "43": active_task}
        manager._ingestors = {"0": ingestor}

        result = manager.stop_task("42")

        self.assertEqual(result["status"], "success")
        self.assertIn("0", manager._ingestors)
        self.assertFalse(manager._tasks["43"].done)
        ingestor.remove_task.assert_called_once_with("Watch for a phone")


if __name__ == "__main__":
    unittest.main()
