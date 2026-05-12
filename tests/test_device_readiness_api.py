import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import flask_app.app as app_module


class DeviceReadinessApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        with app_module._browser_camera_lock:
            app_module._browser_camera_frames.clear()

    def tearDown(self):
        with app_module._browser_camera_lock:
            app_module._browser_camera_frames.clear()

    def test_unknown_device_returns_machine_readable_not_ready(self):
        with (
            patch.object(app_module.io_manager, "get_stream_info", return_value=None),
            patch.object(app_module.task_manager, "peek_ingestor", return_value=None),
        ):
            resp = self.client.get("/api/device/missing-camera/readiness")

        self.assertEqual(resp.status_code, 404)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "not_ready")
        self.assertFalse(body.get("ready"))
        self.assertFalse(body.get("device_exists"))
        self.assertIn("Device is not registered", " ".join(body.get("warnings", [])))

    def test_browser_camera_without_fresh_frames_is_not_ready(self):
        ingestor = MagicMock()
        ingestor._running = True
        ingestor.get_latest_frame.return_value = None
        ingestor.get_latest_frame_timestamp.return_value = None
        ingestor.get_binary_monitor_status.return_value = {"enabled": True}
        ingestor.get_semantic_filter_status.return_value = {"enabled": False}

        device = {
            "io_id": "browser_facetime",
            "name": "Browser FaceTime Camera",
            "source": "network",
            "category": "camera",
            "url": "http://127.0.0.1:5050/api/browser-camera/facetime/latest.jpg",
        }

        with (
            patch.object(app_module.io_manager, "get_stream_info", return_value=device),
            patch.object(app_module.task_manager, "peek_ingestor", return_value=ingestor),
        ):
            resp = self.client.get("/api/device/browser_facetime/readiness")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "not_ready")
        self.assertFalse(body.get("ready"))
        self.assertTrue(body.get("device_exists"))
        self.assertFalse(body.get("browser_camera", {}).get("has_fresh_frame"))
        self.assertIn("Browser camera source has no fresh frames", " ".join(body.get("warnings", [])))

    def test_browser_camera_with_fresh_frames_and_running_ingestor_is_ready(self):
        with app_module._browser_camera_lock:
            app_module._browser_camera_frames["facetime"] = {
                "bytes": b"not-used-by-readiness",
                "timestamp": time.time(),
                "width": 640,
                "height": 480,
                "mean": 64.0,
                "std": 12.0,
            }

        ingestor = MagicMock()
        ingestor._running = True
        ingestor.get_latest_frame.return_value = SimpleNamespace(size=1)
        ingestor.get_latest_frame_timestamp.return_value = time.time()
        ingestor.get_binary_monitor_status.return_value = {
            "enabled": True,
            "condition": "a human is visible",
        }
        ingestor.get_semantic_filter_status.return_value = {"enabled": False}

        device = {
            "io_id": "browser_facetime",
            "name": "Browser FaceTime Camera",
            "source": "network",
            "category": "camera",
            "url": "http://127.0.0.1:5050/api/browser-camera/facetime/latest.jpg",
        }

        with (
            patch.object(app_module.io_manager, "get_stream_info", return_value=device),
            patch.object(app_module.task_manager, "peek_ingestor", return_value=ingestor),
        ):
            resp = self.client.get("/api/device/browser_facetime/readiness")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "ready")
        self.assertTrue(body.get("ready"))
        self.assertTrue(body.get("browser_camera", {}).get("has_fresh_frame"))
        self.assertEqual(body.get("warnings"), [])


if __name__ == "__main__":
    unittest.main()
