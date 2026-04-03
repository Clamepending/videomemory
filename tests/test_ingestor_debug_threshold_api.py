import unittest
from unittest.mock import patch

import flask_app.app as app_module


class IngestorDebugThresholdApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_get_threshold_returns_task_manager_value(self):
        with (
            patch.object(app_module.io_manager, "get_stream_info", return_value={"io_id": "net0"}),
            patch.object(
                app_module.task_manager,
                "get_ingestor_frame_skip_threshold",
                return_value={
                    "io_id": "net0",
                    "average_pixel_diff_threshold": 4.5,
                    "frame_diff_threshold": 4.5,
                    "threshold_unit": "average_pixel_difference_0_to_255",
                    "source": "active_ingestor",
                    "has_ingestor": True,
                },
            ) as get_threshold,
        ):
            resp = self.client.get("/api/device/net0/debug/frame-skip-threshold")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["average_pixel_diff_threshold"], 4.5)
        self.assertEqual(resp.get_json()["frame_diff_threshold"], 4.5)
        get_threshold.assert_called_once_with("net0")

    def test_put_threshold_validates_and_saves_value(self):
        with (
            patch.object(app_module.io_manager, "get_stream_info", return_value={"io_id": "net0"}),
            patch.object(
                app_module.task_manager,
                "set_ingestor_frame_skip_threshold",
                return_value={
                    "io_id": "net0",
                    "average_pixel_diff_threshold": 2.5,
                    "frame_diff_threshold": 2.5,
                    "threshold_unit": "average_pixel_difference_0_to_255",
                    "source": "active_ingestor",
                    "has_ingestor": True,
                },
            ) as set_threshold,
        ):
            resp = self.client.put(
                "/api/device/net0/debug/frame-skip-threshold",
                json={"value": 2.5},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["average_pixel_diff_threshold"], 2.5)
        self.assertEqual(resp.get_json()["frame_diff_threshold"], 2.5)
        set_threshold.assert_called_once_with("net0", 2.5)

    def test_put_threshold_rejects_non_numeric_values(self):
        with patch.object(app_module.io_manager, "get_stream_info", return_value={"io_id": "net0"}):
            resp = self.client.put(
                "/api/device/net0/debug/frame-skip-threshold",
                json={"value": "not-a-number"},
            )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())


if __name__ == "__main__":
    unittest.main()
