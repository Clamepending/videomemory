import os
from unittest.mock import AsyncMock, Mock, patch
import unittest

import numpy as np

from videomemory.system.stream_ingestors.frame_utils import subsample_frames
from videomemory.system.stream_ingestors.binary_monitor import (
    BinaryFrameMonitor,
    BinaryMonitorDecision,
    BinaryMonitorScore,
)
from videomemory.system.stream_ingestors.video_stream_ingestor import VideoStreamIngestor
from videomemory.system.stream_ingestors.prompting import TaskUpdate, VideoIngestorOutput
from videomemory.system.task_types import MONITOR_TYPE_BINARY, MONITOR_TYPE_GENERAL, Task


class VideoStreamIngestorDetectionCallbackTests(unittest.TestCase):
    def test_binary_monitor_defaults_require_stronger_temporal_consensus(self):
        with patch.dict(
            os.environ,
            {
                "VIDEOMEMORY_FASTVLM_THRESHOLD": "",
                "VIDEOMEMORY_FASTVLM_REQUIRED_HITS": "",
                "VIDEOMEMORY_FASTVLM_WINDOW": "",
                "VIDEOMEMORY_FASTVLM_THRESHOLD_MODE": "",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_Z": "",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_MIN_SAMPLES": "",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_WINDOW": "",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_FLOOR": "",
            },
        ):
            monitor = BinaryFrameMonitor(runtime=Mock())

        self.assertEqual(monitor.threshold_mode, "adaptive")
        self.assertEqual(monitor.threshold, 0.7)
        self.assertEqual(monitor.required_hits, 4)
        self.assertEqual(monitor.window, 5)
        self.assertEqual(monitor.adaptive_z, 3.0)
        self.assertEqual(monitor.adaptive_min_samples, 10)
        self.assertEqual(monitor.adaptive_window, 10)
        self.assertEqual(monitor.adaptive_floor, 0.5)

    def test_binary_monitor_env_settings_can_be_reloaded(self):
        monitor = BinaryFrameMonitor(runtime=Mock())

        with patch.dict(
            os.environ,
            {
                "VIDEOMEMORY_FASTVLM_THRESHOLD_MODE": "fixed",
                "VIDEOMEMORY_FASTVLM_THRESHOLD": "0.6",
                "VIDEOMEMORY_FASTVLM_REQUIRED_HITS": "6",
                "VIDEOMEMORY_FASTVLM_WINDOW": "5",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_Z": "2.5",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_MIN_SAMPLES": "4",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_WINDOW": "10",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_FLOOR": "0.4",
            },
        ):
            settings = monitor.reload_settings_from_env()

        self.assertEqual(settings["threshold_mode"], "fixed")
        self.assertEqual(settings["threshold"], 0.6)
        self.assertEqual(settings["required_hits"], 5)
        self.assertEqual(settings["window"], 5)
        self.assertEqual(settings["adaptive_z"], 2.5)
        self.assertEqual(settings["adaptive_min_samples"], 4)
        self.assertEqual(settings["adaptive_window"], 4)
        self.assertEqual(settings["adaptive_floor"], 0.4)

    def test_binary_monitor_adaptive_threshold_uses_frozen_initial_calibration(self):
        class SequenceRuntime:
            def __init__(self):
                self.values = [0.10, 0.12, 0.11, 0.20, 0.90]

            def score_bgr_frame(self, frame, criterion, resize=None):
                p_true = self.values.pop(0)
                return BinaryMonitorScore(
                    answer="True" if p_true >= 0.5 else "False",
                    p_true=p_true,
                    p_false=1.0 - p_true,
                    raw_text="",
                    inference_ms=1.0,
                    model="fake-fastvlm",
                    resize=resize or 256,
                )

        with patch.dict(
            os.environ,
            {
                "VIDEOMEMORY_FASTVLM_THRESHOLD_MODE": "adaptive",
                "VIDEOMEMORY_FASTVLM_THRESHOLD": "0.9",
                "VIDEOMEMORY_FASTVLM_REQUIRED_HITS": "1",
                "VIDEOMEMORY_FASTVLM_WINDOW": "1",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_Z": "3.0",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_MIN_SAMPLES": "3",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_WINDOW": "10",
                "VIDEOMEMORY_FASTVLM_ADAPTIVE_FLOOR": "0.0",
            },
        ):
            monitor = BinaryFrameMonitor(runtime=SequenceRuntime())

        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        task = self._binary_task()
        decisions = [monitor.score_task(frame, task) for _ in range(4)]

        self.assertFalse(decisions[2].done)
        self.assertTrue(decisions[2].calibrating)
        self.assertFalse(decisions[2].adaptive_ready)
        final = decisions[3]
        self.assertTrue(final.adaptive_ready)
        self.assertFalse(final.calibrating)
        self.assertEqual(final.baseline_samples, 3)
        self.assertAlmostEqual(final.baseline_mean, 0.11)
        self.assertAlmostEqual(final.baseline_variance, 0.00006666666666666667)
        self.assertAlmostEqual(final.baseline_stddev, 0.00816496580927726)
        self.assertAlmostEqual(final.effective_threshold, 0.13449489742783178)
        self.assertTrue(final.done)
        after_trigger = monitor.score_task(frame, task)
        self.assertAlmostEqual(after_trigger.baseline_mean, 0.11)
        self.assertAlmostEqual(after_trigger.effective_threshold, final.effective_threshold)

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

    def _binary_task(self):
        return Task(
            task_id="task-binary",
            task_number=0,
            task_desc="a red marker is visible",
            task_note=[],
            done=False,
            io_id="net0",
            monitor_type=MONITOR_TYPE_BINARY,
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

    def test_process_ml_results_attaches_evidence_clip_payload_to_new_note(self):
        updates = []
        ingestor = VideoStreamIngestor(
            "http://camera.example/snapshot.jpg",
            model_provider=object(),
            on_task_updated=lambda task, note: updates.append((task, note)),
        )
        task = self._task()
        ingestor._tasks_list = [task]
        ingestor._evidence_clip_fps = 4.0
        prior_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        prior_frame[:, :] = (0, 0, 255)
        trigger_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        trigger_frame[:, :] = (0, 255, 0)
        ingestor._evidence_frame_buffer.append((1.0, prior_frame.copy()))

        ingestor._process_ml_results(
            {
                "frame": trigger_frame,
                "task_updates": [
                    {
                        "task_number": 0,
                        "task_note": "Red marker detected in frame.",
                        "task_done": False,
                    }
                ],
            }
        )

        note = task.task_note[0]
        video_frames, video_fps = note.consume_video_payload()
        self.assertIsNotNone(video_frames)
        self.assertGreaterEqual(len(video_frames), 2)
        self.assertEqual(video_fps, 4.0)
        self.assertTrue(np.array_equal(video_frames[0], prior_frame))
        self.assertTrue(np.array_equal(video_frames[-1], trigger_frame))
        self.assertEqual(len(updates), 1)
        self.assertIs(updates[0][1], note)

    def test_vlm_processing_uses_queued_evidence_snapshot_for_note_video(self):
        provider = Mock()
        provider._sync_generate_content.return_value = VideoIngestorOutput(
            task_updates=[
                TaskUpdate(
                    task_number=0,
                    task_note="Red marker detected in frame.",
                    task_done=False,
                )
            ]
        )
        ingestor = VideoStreamIngestor("http://camera.example/snapshot.jpg", model_provider=provider)
        task = self._task()
        ingestor._tasks_list = [task]
        ingestor._evidence_clip_fps = 4.0
        ingestor._evidence_clip_end_hold_seconds = 0.0
        prior_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        prior_frame[:, :] = (0, 0, 255)
        trigger_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        trigger_frame[:, :] = (0, 255, 0)
        future_frame = np.zeros((12, 16, 3), dtype=np.uint8)
        future_frame[:, :] = (255, 0, 0)
        ingestor._evidence_frame_buffer.append((99.0, future_frame.copy()))

        result = ingestor._VLM_processing(
            [prior_frame.copy(), trigger_frame.copy()],
            evidence_buffer_snapshot=[
                (1.0, prior_frame.copy()),
                (2.0, trigger_frame.copy()),
            ],
        )

        self.assertIsNotNone(result)
        note = task.task_note[0]
        video_frames, video_fps = note.consume_video_payload()
        self.assertIsNotNone(video_frames)
        self.assertEqual(video_fps, 4.0)
        self.assertTrue(any(np.array_equal(frame, prior_frame) for frame in video_frames))
        self.assertTrue(np.array_equal(video_frames[-1], trigger_frame))
        self.assertFalse(any(np.array_equal(frame, future_frame) for frame in video_frames))

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

    def test_vlm_processing_subsamples_when_chunk_exceeds_max_frame_cap(self):
        provider = Mock()
        provider._sync_generate_content.return_value = VideoIngestorOutput(task_updates=[])
        ingestor = VideoStreamIngestor("http://camera.example/snapshot.jpg", model_provider=provider)
        ingestor._tasks_list = [self._task()]
        ingestor._video_chunk_subsample_frames = 3

        frames = []
        for value in range(5):
            frame = np.zeros((12, 16, 3), dtype=np.uint8)
            frame[:, :] = value * 40
            frames.append(frame)

        result = ingestor._VLM_processing(frames)

        self.assertIsNotNone(result)
        self.assertEqual(result["chunk"]["duration_seconds"], 2.0)
        self.assertEqual(result["chunk"]["sampled_frame_count"], 3)
        self.assertEqual(result["chunk"]["raw_frame_count"], 5)
        self.assertEqual(result["frame"].shape, (480, 640, 3))
        self.assertIn("chronological contact sheet of 3", provider._sync_generate_content.call_args.kwargs["prompt"])
        self.assertIn("2.00s video chunk", provider._sync_generate_content.call_args.kwargs["prompt"])

        latest_model_input = ingestor.get_latest_model_input()
        self.assertIsNotNone(latest_model_input)
        self.assertEqual(latest_model_input["chunk"]["sampled_frame_count"], 3)

    def test_vlm_processing_uses_all_frames_when_below_frame_cap(self):
        provider = Mock()
        provider._sync_generate_content.return_value = VideoIngestorOutput(task_updates=[])
        ingestor = VideoStreamIngestor("http://camera.example/snapshot.jpg", model_provider=provider)
        ingestor._tasks_list = [self._task()]
        ingestor._video_chunk_subsample_frames = 8

        frames = []
        for value in range(5):
            frame = np.zeros((12, 16, 3), dtype=np.uint8)
            frame[:, :] = value * 40
            frames.append(frame)

        result = ingestor._VLM_processing(frames)

        self.assertIsNotNone(result)
        self.assertEqual(result["chunk"]["sampled_frame_count"], 5)
        self.assertEqual(result["chunk"]["raw_frame_count"], 5)
        self.assertIn("chronological contact sheet of 5", provider._sync_generate_content.call_args.kwargs["prompt"])

    def test_vlm_processing_records_model_input_when_provider_fails(self):
        provider = Mock()
        provider._sync_generate_content.side_effect = RuntimeError("provider down")
        ingestor = VideoStreamIngestor("http://camera.example/snapshot.jpg", model_provider=provider)
        ingestor._tasks_list = [self._task()]

        frames = [np.zeros((12, 16, 3), dtype=np.uint8) for _ in range(4)]

        result = ingestor._VLM_processing(frames)

        self.assertIsNone(result)
        latest_model_input = ingestor.get_latest_model_input()
        self.assertIsNotNone(latest_model_input)
        self.assertEqual(latest_model_input["chunk"]["sampled_frame_count"], 4)
        self.assertIsNotNone(ingestor.get_latest_inference_error())

    def test_subsample_frames_keeps_evenly_spaced_frames(self):
        frames = []
        for value in range(5):
            frame = np.zeros((1, 1, 3), dtype=np.uint8)
            frame[:, :] = value
            frames.append(frame)

        sampled = subsample_frames(frames, 3)

        self.assertEqual([int(frame[0, 0, 0]) for frame in sampled], [0, 2, 4])

    def test_chunk_keeps_duplicate_frames_after_motion_trigger(self):
        ingestor = VideoStreamIngestor("http://camera.example/snapshot.jpg", model_provider=object())
        ingestor._tasks_list = [self._task()]
        ingestor._frame_diff_threshold = 5.0
        first = np.zeros((2, 2, 3), dtype=np.uint8)
        duplicate = first.copy()

        chunk_frames = []
        first_has_motion = ingestor._add_frame_to_chunk(chunk_frames, first)
        duplicate_has_motion = ingestor._add_frame_to_chunk(chunk_frames, duplicate)

        self.assertTrue(first_has_motion)
        self.assertFalse(duplicate_has_motion)
        self.assertEqual(len(chunk_frames), 2)

    def test_binary_monitor_tasks_are_not_sent_to_general_vlm_provider(self):
        provider = Mock()
        ingestor = VideoStreamIngestor("http://camera.example/snapshot.jpg", model_provider=provider)
        ingestor._tasks_list = [self._binary_task()]

        result = ingestor._VLM_processing([np.zeros((12, 16, 3), dtype=np.uint8)])

        self.assertIsNone(result)
        provider._sync_generate_content.assert_not_called()

    def test_binary_monitor_done_updates_task_without_general_provider(self):
        class FakeBinaryMonitor:
            threshold = 0.7
            required_hits = 4
            window = 5
            resize = 256

            def __init__(self):
                self.reset_task_calls = []

            def score_task(self, frame, task):
                return BinaryMonitorDecision(
                    task_id=str(task.task_id),
                    criterion=task.task_desc,
                    score=BinaryMonitorScore(
                        answer="True",
                        p_true=0.91,
                        p_false=0.09,
                        raw_text="True",
                        inference_ms=12.0,
                        model="fake-fastvlm",
                        resize=256,
                    ),
                    threshold=0.7,
                    required_hits=4,
                    window=5,
                    hits=4,
                    done=True,
                )

            def reset_task(self, task_id):
                self.reset_task_calls.append(task_id)

        updates = []
        detections = []
        provider = Mock()
        ingestor = VideoStreamIngestor(
            "http://camera.example/snapshot.jpg",
            model_provider=provider,
            on_task_updated=lambda task, note: updates.append((task, note)),
            on_detection_event=lambda task, note: detections.append((task, note)),
        )
        fake_monitor = FakeBinaryMonitor()
        ingestor._binary_monitor = fake_monitor
        task = self._binary_task()
        ingestor._tasks_list = [task]
        frame = np.zeros((12, 16, 3), dtype=np.uint8)

        ingestor._process_binary_monitor_frame(frame)

        self.assertTrue(task.done)
        self.assertEqual(len(task.task_note), 1)
        self.assertIn("Binary criterion met", task.task_note[0].content)
        self.assertEqual(ingestor._tasks_list, [])
        self.assertEqual(fake_monitor.reset_task_calls, ["task-binary"])
        provider._sync_generate_content.assert_not_called()
        self.assertEqual(len(updates), 1)
        self.assertEqual(len(detections), 1)


class VideoStreamIngestorStartupTests(unittest.IsolatedAsyncioTestCase):
    def test_open_camera_releases_failed_local_capture_handle(self):
        ingestor = VideoStreamIngestor(0, model_provider=object())
        fake_cap = Mock()
        fake_cap.isOpened.return_value = False

        with (
            patch("videomemory.system.stream_ingestors.video_stream_ingestor.platform.system", return_value="Linux"),
            patch("videomemory.system.stream_ingestors.video_stream_ingestor.cv2.VideoCapture", return_value=fake_cap),
        ):
            opened = ingestor._open_camera()

        self.assertFalse(opened)
        fake_cap.release.assert_called_once()
        self.assertIsNone(ingestor._camera)

    async def test_ensure_camera_open_retries_local_camera_transient_failure(self):
        ingestor = VideoStreamIngestor(0, model_provider=object())
        ingestor._running = True
        attempts = []

        def fake_open_camera():
            attempts.append(True)
            return len(attempts) >= 2

        with (
            patch.object(ingestor, "_open_camera", side_effect=fake_open_camera),
            patch.dict(
                os.environ,
                {
                    "VIDEOMEMORY_LOCAL_CAMERA_OPEN_RETRY_COUNT": "2",
                    "VIDEOMEMORY_LOCAL_CAMERA_RETRY_SECONDS": "0",
                },
                clear=False,
            ),
        ):
            opened = await ingestor._ensure_camera_open()

        self.assertTrue(opened)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(ingestor.get_tasks_list(), [])

    async def test_start_clears_running_state_when_camera_never_opens(self):
        ingestor = VideoStreamIngestor(0, model_provider=object())

        with patch.object(ingestor, "_ensure_camera_open", AsyncMock(return_value=False)):
            await ingestor.start()

        self.assertFalse(ingestor._running)
        self.assertIsNone(ingestor._loop)

    def test_ensure_started_uses_shared_background_loop_when_no_running_loop(self):
        ingestor = VideoStreamIngestor(0, model_provider=object())
        fake_loop = Mock()
        fake_loop.is_running.return_value = True

        with (
            patch("videomemory.system.stream_ingestors.video_stream_ingestor.asyncio.get_running_loop", side_effect=RuntimeError),
            patch("videomemory.system.stream_ingestors.video_stream_ingestor.get_background_loop", return_value=fake_loop),
            patch("videomemory.system.stream_ingestors.video_stream_ingestor.asyncio.run_coroutine_threadsafe") as mock_run_threadsafe,
        ):
            ingestor.ensure_started()

        mock_run_threadsafe.assert_called_once()
        scheduled_coro = mock_run_threadsafe.call_args.args[0]
        self.assertIs(mock_run_threadsafe.call_args.args[1], fake_loop)
        scheduled_coro.close()


if __name__ == "__main__":
    unittest.main()
