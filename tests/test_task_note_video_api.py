import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask_app import app as app_module


class TaskNoteVideoApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_get_task_note_video_serves_mp4_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "note_7.mp4"
            video_path.write_bytes(b"fake-mp4-bytes")

            with patch.object(app_module.db, "get_note_video_path", return_value=video_path):
                resp = self.client.get("/api/task-note/7/video")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "video/mp4")
        self.assertEqual(resp.data, b"fake-mp4-bytes")
        resp.close()

    def test_get_task_note_video_returns_404_when_missing(self):
        with patch.object(app_module.db, "get_note_video_path", return_value=None):
            resp = self.client.get("/api/task-note/7/video")

        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
