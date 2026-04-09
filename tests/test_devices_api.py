import unittest
from types import SimpleNamespace
from unittest.mock import patch

import flask_app.app as app_module


class DevicesApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_devices_api_includes_ingestor_state_per_device(self):
        devices = [
            {"io_id": "0", "name": "USB Webcam", "category": "camera", "source": "local"},
            {"io_id": "net0", "name": "Phone Camera", "category": "camera", "source": "network", "url": "http://cam.test/mjpeg"},
            {"io_id": "mic0", "name": "Desk Mic", "category": "audio", "source": "local"},
        ]

        def fake_get_ingestor(io_id):
            if io_id == "0":
                return SimpleNamespace(_running=True)
            if io_id == "net0":
                return SimpleNamespace(_running=False)
            return None

        with (
            patch.object(app_module.io_manager, "_refresh_streams", return_value=True),
            patch.object(app_module.io_manager, "list_all_streams", return_value=devices),
            patch.object(app_module.task_manager, "get_ingestor", side_effect=fake_get_ingestor),
        ):
            resp = self.client.get("/api/devices")

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        camera_entries = {item["io_id"]: item for item in body["devices"]["camera"]}
        audio_entries = {item["io_id"]: item for item in body["devices"]["audio"]}

        self.assertEqual(camera_entries["0"]["ingestor_state"], "running")
        self.assertTrue(camera_entries["0"]["ingestor_running"])

        self.assertEqual(camera_entries["net0"]["ingestor_state"], "stopped")
        self.assertFalse(camera_entries["net0"]["ingestor_running"])
        self.assertEqual(camera_entries["net0"]["url"], "http://cam.test/mjpeg")

        self.assertEqual(audio_entries["mic0"]["ingestor_state"], "idle")
        self.assertFalse(audio_entries["mic0"]["ingestor_running"])


if __name__ == "__main__":
    unittest.main()
