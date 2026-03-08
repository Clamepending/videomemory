import unittest
from unittest.mock import patch

from flask_app import app as flask_app_module
from videomemory.system.io_manager.manager import IOmanager


class RtmpCameraIdTests(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()

    @patch.object(flask_app_module, "_rtmp_port_diagnostics", return_value={"rtmp_port_ok": True})
    @patch.object(flask_app_module, "_ingest_internal_host", return_value="127.0.0.1")
    @patch.object(flask_app_module, "_rtmp_url_host", return_value="10.0.0.5")
    @patch.object(flask_app_module.io_manager, "get_stream_info", return_value={"pull_url": "rtsp://127.0.0.1:8554/live/frontdoor_cam"})
    @patch.object(flask_app_module.io_manager, "add_network_camera")
    def test_create_rtmp_camera_uses_device_name_as_io_id(
        self,
        mock_add_network_camera,
        _mock_get_stream_info,
        _mock_public_host,
        _mock_internal_host,
        _mock_rtmp_diag,
    ):
        mock_add_network_camera.return_value = {
            "io_id": "frontdoor_cam",
            "category": "camera",
            "name": "frontdoor_cam",
            "source": "network",
            "url": "rtmp://127.0.0.1:1935/live/frontdoor-cam",
        }

        resp = self.client.post("/api/devices/network/rtmp", json={"device_name": "frontdoor_cam"})
        self.assertEqual(resp.status_code, 200)

        _args, kwargs = mock_add_network_camera.call_args
        self.assertEqual(kwargs.get("io_id"), "frontdoor_cam")

        payload = resp.get_json()
        self.assertEqual(payload.get("status"), "success")
        self.assertEqual(payload.get("device", {}).get("io_id"), "frontdoor_cam")

    @patch("videomemory.system.io_manager.manager.DeviceDetector.detect_all", return_value={"camera": []})
    def test_io_manager_accepts_explicit_network_io_id(self, _mock_detect_all):
        manager = IOmanager(db=None)
        camera = manager.add_network_camera(
            "rtmp://127.0.0.1:1935/live/frontdoor-cam",
            "Front Door Camera",
            io_id="frontdoor_cam",
        )
        self.assertEqual(camera["io_id"], "frontdoor_cam")

    @patch("videomemory.system.io_manager.manager.DeviceDetector.detect_all", return_value={"camera": []})
    def test_io_manager_rejects_conflicting_explicit_network_io_id(self, _mock_detect_all):
        manager = IOmanager(db=None)
        manager.add_network_camera(
            "rtmp://127.0.0.1:1935/live/frontdoor-cam",
            "Front Door Camera",
            io_id="frontdoor_cam",
        )

        with self.assertRaises(ValueError):
            manager.add_network_camera(
                "rtmp://127.0.0.1:1935/live/backyard-cam",
                "Backyard Camera",
                io_id="frontdoor_cam",
            )


if __name__ == "__main__":
    unittest.main()
