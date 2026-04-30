import os
import unittest
from unittest.mock import Mock, patch

import numpy as np

import flask_app.app as app_module
from videomemory.system.task_manager import TaskManager


def _make_test_frame() -> np.ndarray:
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    frame[:, :] = (60, 140, 220)
    return frame


class TaskManagerLocalPreviewLeaseTests(unittest.TestCase):
    @patch("videomemory.system.task_manager.VideoStreamIngestor")
    def test_ensure_device_ingestor_allows_local_keep_alive_override(self, mock_ingestor_cls):
        io_manager = Mock()
        io_manager.get_stream_info.return_value = {
            "io_id": "0",
            "category": "camera",
            "name": "USB Webcam",
            "source": "local",
        }
        io_manager.is_network_camera.return_value = False
        io_manager._detector.detect_cameras.return_value = [(0, "USB Webcam")]

        ingestor = Mock()
        mock_ingestor_cls.return_value = ingestor

        manager = TaskManager(io_manager=io_manager, model_provider=object(), db=None)
        result = manager.ensure_device_ingestor("0", keep_alive_without_tasks=True)

        self.assertIs(result, ingestor)
        ingestor.set_keep_alive_without_tasks.assert_any_call(True)
        ingestor.ensure_started.assert_called_once()


class LocalCameraPreviewIngestorTests(unittest.TestCase):
    def setUp(self):
        app_module._local_preview_ingestor_leases.clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module._local_preview_ingestor_leases.clear()

    def test_release_local_preview_ingestor_waits_for_last_preview_lease(self):
        app_module._local_preview_ingestor_leases["0"] = 2

        with (
            patch.object(app_module.task_manager, "get_ingestor") as mock_get_ingestor,
            patch.object(app_module.task_manager, "release_device_ingestor") as mock_release,
        ):
            app_module._release_local_preview_ingestor("0")

        self.assertEqual(app_module._local_preview_ingestor_leases["0"], 1)
        mock_get_ingestor.assert_not_called()
        mock_release.assert_not_called()

    def test_release_local_preview_ingestor_keeps_active_task_ingestor_running(self):
        app_module._local_preview_ingestor_leases["0"] = 1
        ingestor = Mock()

        with (
            patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor),
            patch.object(
                app_module.task_manager,
                "list_tasks",
                return_value=[{"task_id": "1", "status": "active"}],
            ),
            patch.object(app_module.task_manager, "release_device_ingestor") as mock_release,
        ):
            app_module._release_local_preview_ingestor("0")

        self.assertNotIn("0", app_module._local_preview_ingestor_leases)
        ingestor.set_keep_alive_without_tasks.assert_called_once_with(False)
        mock_release.assert_not_called()

    @patch.dict(os.environ, {"VIDEOMEMORY_LOCAL_PREVIEW_WARMUP_S": "0"}, clear=False)
    def test_preview_endpoint_uses_shared_local_ingestor_without_direct_capture(self):
        frame = _make_test_frame()
        shared_ingestor = Mock()

        with (
            patch.object(
                app_module.io_manager,
                "get_stream_info",
                return_value={
                    "io_id": "0",
                    "category": "camera",
                    "name": "USB Webcam",
                    "source": "local",
                },
            ),
            patch.object(
                app_module.task_manager,
                "get_latest_frame_for_device",
                side_effect=[None, frame],
            ),
            patch.object(
                app_module.task_manager,
                "ensure_device_ingestor",
                return_value=shared_ingestor,
            ) as mock_ensure,
            patch.object(app_module.task_manager, "get_ingestor", return_value=shared_ingestor),
            patch.object(app_module.task_manager, "list_tasks", return_value=[]),
            patch.object(app_module.task_manager, "release_device_ingestor", return_value=True) as mock_release,
            patch.object(
                app_module,
                "_get_camera_preview_frame",
                side_effect=AssertionError("local preview should not open the camera directly"),
            ),
        ):
            resp = self.client.get("/api/device/0/preview")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "image/jpeg")
        self.assertGreater(len(resp.data), 0)
        mock_ensure.assert_called_once_with("0", keep_alive_without_tasks=True)
        shared_ingestor.set_keep_alive_without_tasks.assert_called_once_with(False)
        mock_release.assert_called_once_with("0")

    @patch.dict(
        os.environ,
        {
            "VIDEOMEMORY_LOCAL_PREVIEW_WARMUP_S": "0",
            "VIDEOMEMORY_PREVIEW_STREAM_FPS": "20",
        },
        clear=False,
    )
    def test_preview_stream_uses_shared_local_ingestor_without_direct_videocapture(self):
        frame = _make_test_frame()

        with (
            patch.object(
                app_module.io_manager,
                "get_stream_info",
                return_value={
                    "io_id": "0",
                    "category": "camera",
                    "name": "USB Webcam",
                    "source": "local",
                },
            ),
            patch.object(
                app_module.task_manager,
                "get_latest_frame_for_device",
                side_effect=[None, frame, frame],
            ),
            patch.object(app_module, "_acquire_local_preview_ingestor", return_value=object()) as mock_acquire,
            patch.object(app_module, "_release_local_preview_ingestor") as mock_release,
            patch.object(
                app_module.cv2,
                "VideoCapture",
                side_effect=AssertionError("local preview stream should not open VideoCapture directly"),
            ),
        ):
            resp = self.client.get("/api/device/0/preview/stream", buffered=False)
            try:
                first_chunk = next(resp.response)
            finally:
                resp.close()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "multipart/x-mixed-replace")
        self.assertIn(b"--frame", first_chunk)
        self.assertIn(b"Content-Type: image/jpeg", first_chunk)
        mock_acquire.assert_called_once()
        mock_release.assert_called_once_with("0")


if __name__ == "__main__":
    unittest.main()
