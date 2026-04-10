import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from videomemory.system.database import TaskDatabase
from videomemory.system.task_types import STATUS_ACTIVE, Task


class TaskNoteVideoPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "videomemory.db")
        self.db = TaskDatabase(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _task(self) -> Task:
        return Task(
            task_id="1",
            task_number=0,
            task_desc="Watch for a card on the desk",
            task_note=[],
            done=False,
            io_id="net0",
            status=STATUS_ACTIVE,
        )

    def _frames(self):
        frames = []
        for index in range(4):
            frame = np.zeros((24, 32, 3), dtype=np.uint8)
            frame[:, :] = (index * 40, 120, 220 - index * 30)
            frames.append(frame)
        return frames

    def test_save_note_persists_video_and_loads_it_back(self):
        task = self._task()
        self.db.save_task(task)

        save_result = self.db.save_note(
            task.task_id,
            "A gold card is visible on the desk.",
            1_700_000_000.0,
            video_frames=self._frames(),
            video_fps=4.0,
        )

        self.assertIsNotNone(save_result["note_id"])
        self.assertTrue(save_result["video_path"].startswith("task_note_videos/1/"))

        loaded_tasks = self.db.load_all_tasks()
        self.assertEqual(len(loaded_tasks), 1)
        loaded_notes = loaded_tasks[0]["notes"]
        self.assertEqual(len(loaded_notes), 1)
        self.assertEqual(loaded_notes[0]["note_id"], save_result["note_id"])
        self.assertEqual(loaded_notes[0]["video_path"], save_result["video_path"])

        video_path = self.db.get_note_video_path(save_result["note_id"])
        self.assertIsNotNone(video_path)
        self.assertTrue(video_path.exists())
        self.assertGreater(video_path.stat().st_size, 0)

    def test_delete_task_removes_saved_note_videos(self):
        task = self._task()
        self.db.save_task(task)

        save_result = self.db.save_note(
            task.task_id,
            "Card still visible.",
            1_700_000_001.0,
            video_frames=self._frames(),
            video_fps=4.0,
        )
        video_path = self.db.get_note_video_path(save_result["note_id"])
        self.assertTrue(video_path.exists())

        self.db.delete_task(task.task_id)

        self.assertFalse(video_path.exists())
        self.assertIsNone(self.db.get_note_video_path(save_result["note_id"]))

    def test_save_note_prefers_ffmpeg_browser_friendly_mp4_when_available(self):
        task = self._task()
        self.db.save_task(task)

        with patch.object(self.db, "_write_note_video_with_ffmpeg", return_value=True) as mock_ffmpeg:
            save_result = self.db.save_note(
                task.task_id,
                "A gold card is visible on the desk.",
                1_700_000_000.0,
                video_frames=self._frames(),
                video_fps=4.0,
            )

        self.assertTrue(save_result["video_path"].endswith(".mp4"))
        mock_ffmpeg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
