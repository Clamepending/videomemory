import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from flask_app import app as app_module
from videomemory.system.task_types import NoteEntry, Task


class IngestorDebugApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def _write_test_jpeg(self, tmpdir: str) -> Path:
        image = np.zeros((12, 16, 3), dtype=np.uint8)
        image[:, :] = (15, 120, 220)
        ok, buffer = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        path = Path(tmpdir) / "note.jpg"
        path.write_bytes(buffer.tobytes())
        return path

    def test_debug_status_reports_persisted_artifact_without_ingestor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_path = self._write_test_jpeg(tmpdir)
            task = Task(
                task_number=0,
                task_id="1",
                task_desc="count desk items",
                task_note=[
                    NoteEntry(
                        content="Desk unchanged",
                        timestamp=1712609854.0,
                        note_id=7,
                        frame_path="task_note_frames/1/note_7.jpg",
                    )
                ],
                done=False,
                io_id="net0",
            )

            with (
                patch.object(app_module.task_manager, "has_ingestor", return_value=False),
                patch.object(app_module.task_manager, "get_ingestor", return_value=None),
                patch.object(app_module.task_manager, "get_task_objects", return_value=[task]),
                patch.object(app_module.db, "get_note_frame_path", return_value=frame_path),
            ):
                resp = self.client.get("/api/device/net0/debug/status")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["has_ingestor"], False)
        self.assertEqual(data["running"], False)
        self.assertEqual(data["has_debug_artifact"], True)

    def test_debug_frame_endpoint_falls_back_to_persisted_note_frame(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_path = self._write_test_jpeg(tmpdir)
            task = Task(
                task_number=0,
                task_id="1",
                task_desc="count desk items",
                task_note=[
                    NoteEntry(
                        content="Desk unchanged",
                        timestamp=1712609854.0,
                        note_id=7,
                        frame_path="task_note_frames/1/note_7.jpg",
                    )
                ],
                done=False,
                io_id="net0",
            )

            with (
                patch.object(app_module.task_manager, "get_ingestor", return_value=None),
                patch.object(app_module.task_manager, "get_task_objects", return_value=[task]),
                patch.object(app_module.db, "get_note_frame_path", return_value=frame_path),
            ):
                resp = self.client.get("/api/device/net0/debug/frame-and-prompt")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "persisted_note_frame")
        self.assertTrue(data["frame_base64"])
        self.assertIn("count desk items", data["prompt"])
        self.assertIn("note-backed", data["prompt_notice"])
        self.assertIn("Showing most recent note-backed frame", data["source_label"])

    def test_debug_frame_endpoint_uses_persisted_frame_when_live_output_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_path = self._write_test_jpeg(tmpdir)
            task = Task(
                task_number=0,
                task_id="1",
                task_desc="count desk items",
                task_note=[
                    NoteEntry(
                        content="Desk unchanged",
                        timestamp=1712609854.0,
                        note_id=7,
                        frame_path="task_note_frames/1/note_7.jpg",
                    )
                ],
                done=False,
                io_id="net0",
            )
            ingestor = SimpleNamespace(
                _running=True,
                get_latest_output=lambda: None,
                get_dedup_status=lambda: {"consecutive_skips": 4, "average_pixel_diff_threshold": 3.0},
                get_tasks_list=lambda: [task],
            )

            with (
                patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor),
                patch.object(app_module.task_manager, "get_task_objects", return_value=[task]),
                patch.object(app_module.db, "get_note_frame_path", return_value=frame_path),
            ):
                resp = self.client.get("/api/device/net0/debug/frame-and-prompt")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "persisted_note_frame")
        self.assertEqual(data["dedup_status"]["consecutive_skips"], 4)
        self.assertIn("count desk items", data["prompt"])

    def test_debug_tasks_endpoint_falls_back_to_task_manager_when_ingestor_has_no_tasks(self):
        task = Task(
            task_number=0,
            task_id="1",
            task_desc="count desk items",
            task_note=[NoteEntry(content="Desk unchanged", timestamp=1712609854.0)],
            done=False,
            io_id="net0",
        )
        ingestor = SimpleNamespace(get_tasks_list=lambda: [])

        with (
            patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor),
            patch.object(app_module.task_manager, "get_task_objects", return_value=[task]),
        ):
            resp = self.client.get("/api/device/net0/debug/tasks")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["task_desc"], "count desk items")
        self.assertEqual(data["tasks"][0]["latest_note"]["content"], "Desk unchanged")

    def test_debug_page_template_avoids_nullish_coalescing_for_browser_compatibility(self):
        resp = self.client.get("/device/net0/debug")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn("??", html)


if __name__ == "__main__":
    unittest.main()
