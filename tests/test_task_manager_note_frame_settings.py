import unittest
from unittest.mock import MagicMock

from videomemory.system.task_manager import TaskManager
from videomemory.system.task_types import NoteEntry, STATUS_ACTIVE, Task


class TaskManagerNoteFrameSettingTests(unittest.TestCase):
    def _make_db(self, setting_value: str, frame_path):
        db = MagicMock()
        db.terminate_active_tasks.return_value = 0
        db.load_all_tasks.return_value = []
        db.get_max_task_id.return_value = -1
        db.get_setting.return_value = setting_value
        db.save_note.return_value = {"note_id": 7, "frame_path": frame_path}
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

    def test_on_task_updated_skips_note_frame_storage_when_disabled(self):
        db = self._make_db("0", None)
        manager = TaskManager(io_manager=None, model_provider=object(), db=db)
        task = self._make_task()
        note = NoteEntry(content="Card detected", frame_bytes=b"jpeg-bytes")

        manager._on_task_updated(task, note)

        self.assertEqual(db.save_note.call_args.kwargs["frame_bytes"], None)
        self.assertEqual(note.note_id, 7)
        self.assertIsNone(note.frame_path)

    def test_on_task_updated_persists_note_frame_when_enabled(self):
        db = self._make_db("1", "task_note_frames/task-1/note_7.jpg")
        manager = TaskManager(io_manager=None, model_provider=object(), db=db)
        task = self._make_task()
        note = NoteEntry(content="Card detected", frame_bytes=b"jpeg-bytes")

        manager._on_task_updated(task, note)

        self.assertEqual(db.save_note.call_args.kwargs["frame_bytes"], b"jpeg-bytes")
        self.assertEqual(note.note_id, 7)
        self.assertEqual(note.frame_path, "task_note_frames/task-1/note_7.jpg")


if __name__ == "__main__":
    unittest.main()
