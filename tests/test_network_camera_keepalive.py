import os
import unittest
from unittest.mock import Mock, patch

import flask_app.app as app_module
from videomemory.system.task_manager import TaskManager


class TaskManagerWarmNetworkCameraTests(unittest.TestCase):
    @patch.dict(os.environ, {"VIDEOMEMORY_KEEP_NETWORK_CAMERAS_WARM": "1"}, clear=False)
    @patch("videomemory.system.task_manager.VideoStreamIngestor")
    def test_ensure_device_ingestor_starts_and_warms_network_camera(self, mock_ingestor_cls):
        io_manager = Mock()
        io_manager.get_stream_info.return_value = {
            "io_id": "net0",
            "category": "camera",
            "name": "Phone Camera",
            "url": "http://phone.example/mjpegfeed",
            "pull_url": "http://phone.example/mjpegfeed",
            "source": "network",
        }
        io_manager.is_network_camera.return_value = True

        ingestor = Mock()
        mock_ingestor_cls.return_value = ingestor

        manager = TaskManager(io_manager=io_manager, model_provider=object(), db=None)
        result = manager.ensure_device_ingestor("net0")

        self.assertIs(result, ingestor)
        ingestor.set_keep_alive_without_tasks.assert_any_call(True)
        ingestor.ensure_started.assert_called_once()

    @patch.dict(os.environ, {"VIDEOMEMORY_KEEP_NETWORK_CAMERAS_WARM": "1"}, clear=False)
    @patch("videomemory.system.task_manager.VideoStreamIngestor")
    def test_stop_task_keeps_network_ingestor_registered(self, mock_ingestor_cls):
        io_manager = Mock()
        io_manager.get_stream_info.return_value = {
            "io_id": "net0",
            "category": "camera",
            "name": "Phone Camera",
            "url": "http://phone.example/mjpegfeed",
            "pull_url": "http://phone.example/mjpegfeed",
            "source": "network",
        }
        io_manager.is_network_camera.return_value = True

        ingestor = Mock()
        mock_ingestor_cls.return_value = ingestor

        manager = TaskManager(io_manager=io_manager, model_provider=object(), db=None)
        add_result = manager.add_task("net0", "Watch the driveway")
        stop_result = manager.stop_task(add_result["task_id"])

        self.assertEqual(stop_result["status"], "success")
        self.assertTrue(manager.has_ingestor("net0"))
        ingestor.remove_task.assert_called_once_with("Watch the driveway")


class NetworkCameraKeepAliveApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_add_network_camera_starts_background_ingestor(self):
        with (
            patch.object(
                app_module.io_manager,
                "add_network_camera",
                return_value={
                    "io_id": "net0",
                    "category": "camera",
                    "name": "Phone Camera",
                    "url": "http://phone.example/mjpegfeed",
                    "source": "network",
                },
            ) as mock_add,
            patch.object(app_module.task_manager, "ensure_device_ingestor", return_value=object()) as mock_ensure,
        ):
            resp = self.client.post(
                "/api/devices/network",
                json={"url": "http://phone.example/mjpegfeed", "name": "Phone Camera"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "success")
        mock_add.assert_called_once_with("http://phone.example/mjpegfeed", "Phone Camera")
        mock_ensure.assert_called_once_with("net0")

    @patch.dict(os.environ, {"VIDEOMEMORY_NETWORK_PREVIEW_WARMUP_S": "0"}, clear=False)
    def test_preview_bytes_warm_network_ingestor_before_fallback(self):
        with (
            patch.object(
                app_module.io_manager,
                "get_stream_info",
                return_value={
                    "io_id": "net0",
                    "category": "camera",
                    "name": "Phone Camera",
                    "pull_url": "http://phone.example/mjpegfeed",
                    "source": "network",
                },
            ),
            patch.object(app_module.task_manager, "get_latest_frame_for_device", return_value=None),
            patch.object(app_module.task_manager, "ensure_device_ingestor", return_value=object()) as mock_ensure,
            patch.object(app_module, "_get_network_preview_frame", return_value=b"jpeg-bytes"),
        ):
            frame_bytes = app_module._get_device_preview_frame_bytes("net0")

        self.assertEqual(frame_bytes, b"jpeg-bytes")
        mock_ensure.assert_called_once_with("net0")


if __name__ == "__main__":
    unittest.main()
