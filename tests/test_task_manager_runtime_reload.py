import unittest
from unittest.mock import MagicMock, Mock, patch

from videomemory.system.task_manager import TaskManager
from videomemory.system.task_types import STATUS_ACTIVE, STATUS_DONE, STATUS_TERMINATED


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

    @patch("videomemory.system.task_manager.get_VLM_provider")
    def test_reload_model_provider_re_attaches_usage_callback(self, mock_get_provider):
        usage_callback = Mock()
        old_provider = Mock()
        new_provider = Mock()
        mock_get_provider.return_value = new_provider

        manager = TaskManager(
            io_manager=None,
            model_provider=old_provider,
            db=None,
            on_model_usage=usage_callback,
        )

        manager.reload_model_provider(model_name="gpt-4o-mini")

        old_provider.set_usage_callback.assert_called_once_with(usage_callback)
        new_provider.set_usage_callback.assert_called_once_with(usage_callback)

    @patch("videomemory.system.task_manager.VideoStreamIngestor")
    def test_load_tasks_from_db_resumes_active_camera_tasks_when_io_manager_available(self, mock_ingestor_cls):
        fake_ingestor = MagicMock()
        mock_ingestor_cls.return_value = fake_ingestor
        io_manager = MagicMock()
        io_manager.get_stream_info.return_value = {"category": "camera", "name": "USB Webcam"}
        io_manager._detector.detect_cameras.return_value = [(0, "USB Webcam")]
        db = MagicMock()
        db.load_all_tasks.return_value = [
            {
                "task_id": "1",
                "task_number": 0,
                "task_desc": "Watch the desk",
                "done": False,
                "status": STATUS_ACTIVE,
                "io_id": "0",
                "notes": [],
            },
            {
                "task_id": "2",
                "task_number": 1,
                "task_desc": "Already done",
                "done": True,
                "status": STATUS_DONE,
                "io_id": "0",
                "notes": [],
            },
        ]
        db.get_max_task_id.return_value = 2
        db.get_ingestor_frame_diff_threshold.return_value = None

        manager = TaskManager(io_manager=io_manager, model_provider=object(), db=db)

        db.terminate_active_tasks.assert_not_called()
        fake_ingestor.add_task.assert_called_once()
        resumed_task = fake_ingestor.add_task.call_args.args[0]
        self.assertEqual(resumed_task.task_id, "1")
        self.assertEqual(manager._tasks["1"].status, STATUS_ACTIVE)
        self.assertEqual(manager._task_counter, 3)

    def test_load_tasks_from_db_terminates_active_tasks_when_device_missing(self):
        io_manager = MagicMock()
        io_manager.get_stream_info.return_value = None
        db = MagicMock()
        db.load_all_tasks.return_value = [
            {
                "task_id": "1",
                "task_number": 0,
                "task_desc": "Watch the desk",
                "done": False,
                "status": STATUS_ACTIVE,
                "io_id": "0",
                "notes": [],
            },
        ]
        db.get_max_task_id.return_value = 1

        manager = TaskManager(io_manager=io_manager, model_provider=object(), db=db)

        db.update_task_status.assert_called_once_with("1", STATUS_TERMINATED)
        self.assertEqual(manager._tasks["1"].status, STATUS_TERMINATED)

    @patch("videomemory.system.task_manager.VideoStreamIngestor")
    def test_get_ingestor_lazily_resumes_restart_terminated_task_when_device_returns(self, mock_ingestor_cls):
        fake_ingestor = MagicMock()
        mock_ingestor_cls.return_value = fake_ingestor
        io_manager = MagicMock()
        io_manager.get_stream_info.side_effect = [
            None,  # startup resume attempt
            {"category": "camera", "name": "USB Webcam"},  # lazy resume
        ]
        io_manager._detector.detect_cameras.return_value = [(0, "USB Webcam")]
        db = MagicMock()
        db.load_all_tasks.return_value = [
            {
                "task_id": "1",
                "task_number": 0,
                "task_desc": "Watch the desk",
                "done": False,
                "status": STATUS_ACTIVE,
                "io_id": "0",
                "notes": [],
            },
        ]
        db.get_max_task_id.return_value = 1
        db.get_ingestor_frame_diff_threshold.return_value = None

        manager = TaskManager(io_manager=io_manager, model_provider=object(), db=db)
        self.assertEqual(manager._tasks["1"].status, STATUS_TERMINATED)

        ingestor = manager.get_ingestor("0")

        self.assertIs(ingestor, fake_ingestor)
        fake_ingestor.add_task.assert_called_once()
        self.assertEqual(manager._tasks["1"].status, STATUS_ACTIVE)
        db.update_task_status.assert_any_call("1", STATUS_TERMINATED)
        db.update_task_status.assert_any_call("1", STATUS_ACTIVE)


if __name__ == "__main__":
    unittest.main()
