import unittest

from videomemory.system.stream_ingestors.video_stream_ingestor import VideoStreamIngestor
from videomemory.system.task_types import Task


class VideoStreamIngestorDetectionCallbackTests(unittest.TestCase):
    def _task(self):
        return Task(
            task_id="task-1",
            task_number=0,
            task_desc="Notify me on Telegram when you see a red marker",
            task_note=[],
            done=False,
            io_id="net0",
            bot_id="openclaw",
        )

    def test_process_ml_results_emits_callbacks_when_task_done_without_new_note(self):
        updates = []
        detections = []
        ingestor = VideoStreamIngestor(
            "http://camera.example/snapshot.jpg",
            model_provider=object(),
            on_task_updated=lambda task, note: updates.append((task, note)),
            on_detection_event=lambda task, note: detections.append((task, note)),
        )
        task = self._task()
        ingestor._tasks_list = [task]

        ingestor._process_ml_results({"task_updates": [{"task_number": 0, "task_note": "", "task_done": True}]})

        self.assertTrue(task.done)
        self.assertEqual(len(task.task_note), 0)
        self.assertEqual(len(updates), 1)
        self.assertIs(updates[0][0], task)
        self.assertIsNone(updates[0][1])
        self.assertEqual(len(detections), 1)
        self.assertIs(detections[0][0], task)
        self.assertIsNone(detections[0][1])
        self.assertEqual(ingestor._tasks_list, [])

    def test_process_ml_results_emits_new_note_to_callbacks(self):
        updates = []
        detections = []
        ingestor = VideoStreamIngestor(
            "http://camera.example/snapshot.jpg",
            model_provider=object(),
            on_task_updated=lambda task, note: updates.append((task, note)),
            on_detection_event=lambda task, note: detections.append((task, note)),
        )
        task = self._task()
        ingestor._tasks_list = [task]

        ingestor._process_ml_results(
            {
                "task_updates": [
                    {
                        "task_number": 0,
                        "task_note": "Red marker detected in frame.",
                        "task_done": True,
                    }
                ]
            }
        )

        self.assertTrue(task.done)
        self.assertEqual(len(task.task_note), 1)
        self.assertEqual(task.task_note[0].content, "Red marker detected in frame.")
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1].content, "Red marker detected in frame.")
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0][1].content, "Red marker detected in frame.")
        self.assertEqual(ingestor._tasks_list, [])

    def test_process_ml_results_prunes_only_completed_tasks_and_renumbers_active_ones(self):
        updates = []
        detections = []
        ingestor = VideoStreamIngestor(
            "http://camera.example/snapshot.jpg",
            model_provider=object(),
            on_task_updated=lambda task, note: updates.append((task, note)),
            on_detection_event=lambda task, note: detections.append((task, note)),
        )
        done_task = self._task()
        done_task.task_id = "task-done"
        done_task.task_number = 0
        keep_task = self._task()
        keep_task.task_id = "task-keep"
        keep_task.task_number = 1
        keep_task.task_desc = "Keep watching for a blue square"
        ingestor._tasks_list = [done_task, keep_task]

        ingestor._process_ml_results(
            {
                "task_updates": [
                    {
                        "task_number": 0,
                        "task_note": "Red marker detected in frame.",
                        "task_done": True,
                    }
                ]
            }
        )

        self.assertTrue(done_task.done)
        self.assertEqual(len(ingestor._tasks_list), 1)
        self.assertIs(ingestor._tasks_list[0], keep_task)
        self.assertEqual(keep_task.task_number, 0)
        self.assertFalse(keep_task.done)


if __name__ == "__main__":
    unittest.main()
