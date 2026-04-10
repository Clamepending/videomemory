import unittest
from unittest.mock import MagicMock

import numpy as np

from videomemory.system.task_manager import TaskManager
from videomemory.system.task_types import NoteEntry, STATUS_ACTIVE, Task


class TaskManagerNoteVideoSettingTests(unittest.TestCase):
    def _make_db(self, *, frame_setting: str = "1", video_setting: str = "0", frame_path=None, video_path=None):
        db = MagicMock()
        db.terminate_active_tasks.return_value = 0
        db.load_all_tasks.return_value = []
        db.get_max_task_id.return_value = -1
        db.get_setting.side_effect = lambda key: {
            "VIDEOMEMORY_SAVE_NOTE_FRAMES": frame_setting,
            "VIDEOMEMORY_SAVE_NOTE_VIDEOS": video_setting,
        }.get(key)
        db.save_note.return_value = {"note_id": 7, "frame_path": frame_path, "video_path": video_path}
        return db

    def _make_task(self):
        return Task(
            task_id="task-1",
            task_number=0,
            task_desc="Watch for a card",
            task_note=[],
            done=False,
            io_id="net0",
            status=STATUS_ACTIVE,
        )

    def _make_note(self):
        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        return NoteEntry(
            content="Card detected",
            frame_bytes=b"jpeg-bytes",
            video_frames=[frame.copy(), frame.copy()],
            video_fps=4.0,
        )

    def test_on_task_updated_skips_note_video_storage_when_disabled(self):
        db = self._make_db(video_setting="0", video_path=None)
        manager = TaskManager(io_manager=None, model_provider=object(), db=db)
        task = self._make_task()
        note = self._make_note()

        manager._on_task_updated(task, note)

        self.assertEqual(db.save_note.call_args.kwargs["video_frames"], None)
        self.assertEqual(db.save_note.call_args.kwargs["video_fps"], None)
        self.assertEqual(note.note_id, 7)
        self.assertIsNone(note.video_path)

    def test_on_task_updated_persists_note_video_when_enabled(self):
        db = self._make_db(video_setting="1", video_path="task_note_videos/task-1/note_7.mp4")
        manager = TaskManager(io_manager=None, model_provider=object(), db=db)
        task = self._make_task()
        note = self._make_note()

        manager._on_task_updated(task, note)

        saved_video_frames = db.save_note.call_args.kwargs["video_frames"]
        self.assertIsNotNone(saved_video_frames)
        self.assertEqual(len(saved_video_frames), 2)
        self.assertEqual(db.save_note.call_args.kwargs["video_fps"], 4.0)
        self.assertEqual(note.note_id, 7)
        self.assertEqual(note.video_path, "task_note_videos/task-1/note_7.mp4")

    def test_on_task_updated_respects_per_task_video_override(self):
        db = self._make_db(video_setting="0", video_path="task_note_videos/task-1/note_7.mp4")
        manager = TaskManager(io_manager=None, model_provider=object(), db=db)
        task = self._make_task()
        task.save_note_videos = True
        note = self._make_note()

        manager._on_task_updated(task, note)

        saved_video_frames = db.save_note.call_args.kwargs["video_frames"]
        self.assertIsNotNone(saved_video_frames)
        self.assertEqual(note.video_path, "task_note_videos/task-1/note_7.mp4")


if __name__ == "__main__":
    unittest.main()
