import tempfile
import unittest
from pathlib import Path

from videomemory.system.database import TaskDatabase
from videomemory.system.task_types import STATUS_ACTIVE, Task


class TaskNoteFramePersistenceTests(unittest.TestCase):
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

    def test_save_note_persists_frame_and_loads_it_back(self):
        task = self._task()
        self.db.save_task(task)

        save_result = self.db.save_note(
            task.task_id,
            "A gold card is visible on the desk.",
            1_700_000_000.0,
            frame_bytes=b"fake-jpeg-bytes",
        )

        self.assertIsNotNone(save_result["note_id"])
        self.assertTrue(save_result["frame_path"].startswith("task_note_frames/1/"))

        loaded_tasks = self.db.load_all_tasks()
        self.assertEqual(len(loaded_tasks), 1)
        loaded_notes = loaded_tasks[0]["notes"]
        self.assertEqual(len(loaded_notes), 1)
        self.assertEqual(loaded_notes[0]["note_id"], save_result["note_id"])
        self.assertEqual(loaded_notes[0]["frame_path"], save_result["frame_path"])

        frame_path = self.db.get_note_frame_path(save_result["note_id"])
        self.assertIsNotNone(frame_path)
        self.assertTrue(frame_path.exists())
        self.assertEqual(frame_path.read_bytes(), b"fake-jpeg-bytes")

    def test_delete_task_removes_saved_note_frames(self):
        task = self._task()
        self.db.save_task(task)

        save_result = self.db.save_note(
            task.task_id,
            "Card still visible.",
            1_700_000_001.0,
            frame_bytes=b"frame-to-delete",
        )
        frame_path = self.db.get_note_frame_path(save_result["note_id"])
        self.assertTrue(frame_path.exists())

        self.db.delete_task(task.task_id)

        self.assertFalse(frame_path.exists())
        self.assertIsNone(self.db.get_note_frame_path(save_result["note_id"]))


if __name__ == "__main__":
    unittest.main()
