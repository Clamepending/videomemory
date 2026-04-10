import tempfile
import unittest
import re
import shutil
import subprocess
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
                get_latest_frame=lambda: None,
                get_latest_frame_timestamp=lambda: None,
                get_latest_inference_error=lambda: None,
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

    def test_debug_frame_endpoint_falls_back_to_latest_live_frame_before_first_vlm_call(self):
        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        frame[:, :] = (25, 90, 210)
        task = Task(
            task_number=0,
            task_id="1",
            task_desc="count desk items",
            task_note=[],
            done=False,
            io_id="0",
        )
        ingestor = SimpleNamespace(
            _running=True,
            get_latest_output=lambda: None,
            get_latest_frame=lambda: frame,
            get_latest_frame_timestamp=lambda: 1712609854.0,
            get_latest_inference_error=lambda: None,
            get_dedup_status=lambda: {"consecutive_skips": 0, "average_pixel_diff_threshold": 3.0},
            get_tasks_list=lambda: [task],
        )

        with patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor):
            resp = self.client.get("/api/device/0/debug/frame-and-prompt")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "live_frame")
        self.assertTrue(data["frame_base64"])
        self.assertIn("count desk items", data["prompt"])
        self.assertIn("first VLM call", data["source_label"])
        self.assertIn("has not been recorded yet", data["prompt_notice"])

    def test_debug_frame_endpoint_prefers_live_frame_when_latest_inference_failed(self):
        stale_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        stale_frame[:, :] = (0, 0, 255)
        live_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        live_frame[:, :] = (0, 255, 0)
        task = Task(
            task_number=0,
            task_id="1",
            task_desc="watch for people",
            task_note=[],
            done=False,
            io_id="0",
        )
        ingestor = SimpleNamespace(
            _running=True,
            get_latest_output=lambda: {
                "frame": stale_frame,
                "prompt": "stale prompt",
                "timestamp": 1712609800.0,
                "task_updates": [],
            },
            get_latest_frame=lambda: live_frame,
            get_latest_frame_timestamp=lambda: 1712609860.0,
            get_latest_inference_error=lambda: {
                "timestamp": 1712609859.0,
                "user_message": "Model quota exceeded. Retry in about 30s.",
                "message": "429 RESOURCE_EXHAUSTED",
            },
            get_dedup_status=lambda: {"consecutive_skips": 0, "average_pixel_diff_threshold": 3.0},
            get_tasks_list=lambda: [task],
        )

        with patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor):
            resp = self.client.get("/api/device/0/debug/frame-and-prompt")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "live_frame")
        self.assertIn("failed", data["source_label"])
        self.assertIn("quota exceeded", data["prompt_notice"].lower())
        self.assertEqual(data["inference_error"]["message"], "429 RESOURCE_EXHAUSTED")

    def test_debug_frame_endpoint_labels_live_frame_as_newer_than_last_vlm_call(self):
        stale_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        stale_frame[:, :] = (0, 0, 255)
        live_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        live_frame[:, :] = (0, 255, 0)
        task = Task(
            task_number=0,
            task_id="1",
            task_desc="watch for people",
            task_note=[],
            done=False,
            io_id="0",
        )
        ingestor = SimpleNamespace(
            _running=True,
            get_latest_output=lambda: {
                "frame": stale_frame,
                "prompt": "stale prompt",
                "timestamp": 1712609800.0,
                "task_updates": [],
            },
            get_latest_frame=lambda: live_frame,
            get_latest_frame_timestamp=lambda: 1712609860.0,
            get_latest_inference_error=lambda: None,
            get_dedup_status=lambda: {"consecutive_skips": 0, "average_pixel_diff_threshold": 3.0},
            get_tasks_list=lambda: [task],
        )

        with patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor):
            resp = self.client.get("/api/device/0/debug/frame-and-prompt")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "live_frame")
        self.assertIn("newer than the last recorded VLM call", data["source_label"])
        self.assertIn("older than this frame", data["prompt_notice"])

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

    def test_debug_status_and_history_include_latest_inference_error(self):
        ingestor = SimpleNamespace(
            _running=True,
            get_output_history=lambda: [],
            get_total_output_count=lambda: 0,
            get_latest_inference_error=lambda: {
                "timestamp": 1712609900.0,
                "user_message": "Model quota exceeded. Retry in about 30s.",
                "message": "429 RESOURCE_EXHAUSTED",
            },
        )

        with (
            patch.object(app_module.task_manager, "has_ingestor", return_value=True),
            patch.object(app_module.task_manager, "get_ingestor", return_value=ingestor),
            patch.object(app_module, "_get_latest_persisted_debug_snapshot", return_value=None),
        ):
            status_resp = self.client.get("/api/device/0/debug/status")
            history_resp = self.client.get("/api/device/0/debug/history")

        self.assertEqual(status_resp.status_code, 200)
        self.assertEqual(history_resp.status_code, 200)
        self.assertEqual(
            status_resp.get_json()["latest_inference_error"]["message"],
            "429 RESOURCE_EXHAUSTED",
        )
        self.assertEqual(
            history_resp.get_json()["latest_inference_error"]["message"],
            "429 RESOURCE_EXHAUSTED",
        )

    def test_debug_page_template_avoids_nullish_coalescing_for_browser_compatibility(self):
        resp = self.client.get("/device/net0/debug")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn("??", html)

    def test_debug_routes_disable_browser_caching(self):
        html_resp = self.client.get("/device/net0/debug")
        self.assertEqual(html_resp.status_code, 200)
        self.assertEqual(html_resp.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(html_resp.headers.get("Pragma"), "no-cache")
        self.assertEqual(html_resp.headers.get("Expires"), "0")

        with (
            patch.object(app_module.task_manager, "has_ingestor", return_value=False),
            patch.object(app_module.task_manager, "get_ingestor", return_value=None),
        ):
            api_resp = self.client.get("/api/device/net0/debug/status")

        self.assertEqual(api_resp.status_code, 200)
        self.assertEqual(api_resp.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(api_resp.headers.get("Pragma"), "no-cache")
        self.assertEqual(api_resp.headers.get("Expires"), "0")

    def test_debug_page_inline_scripts_are_valid_javascript(self):
        if shutil.which("node") is None:
            self.skipTest("node is required for JS syntax validation")

        resp = self.client.get("/device/net0/debug")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
        self.assertGreaterEqual(len(scripts), 1)

        for script in scripts:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
                handle.write(script)
                temp_path = handle.name
            try:
                result = subprocess.run(
                    ["node", "--check", temp_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
