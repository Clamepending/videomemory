"""Task Manager for managing tasks associated with IO streams."""

import asyncio
import logging
import os
import sys
from typing import Dict, List, Optional, Any, Callable
from .stream_ingestors.video_stream_ingestor import VideoStreamIngestor
from .io_manager import IOmanager
from .task_types import NoteEntry, Task, STATUS_ACTIVE, STATUS_DONE, STATUS_TERMINATED
from .database import TaskDatabase
from .model_providers import BaseModelProvider, get_VLM_provider
logger = logging.getLogger('TaskManager')

_NOTE_FRAME_SETTING_KEY = "VIDEOMEMORY_SAVE_NOTE_FRAMES"
_NOTE_VIDEO_SETTING_KEY = "VIDEOMEMORY_SAVE_NOTE_VIDEOS"
_TRUE_SETTING_VALUES = {"1", "true", "yes", "on"}
_FALSE_SETTING_VALUES = {"0", "false", "no", "off"}
_AVERAGE_PIXEL_DIFF_UNIT = "average_pixel_difference_0_to_255"

class TaskManager:
    """Manages tasks and their associations with IO streams."""
    
    def __init__(
        self,
        io_manager: IOmanager = None,
        model_provider: Optional[BaseModelProvider] = None,
        db: Optional[TaskDatabase] = None,
        on_detection_event: Optional[Callable[[Task, Optional[NoteEntry]], None]] = None,
        on_model_usage: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """Initialize the task manager.
        
        Args:
            io_manager: Optional IO manager instance for checking stream categories
            model_provider: Optional model provider for ML inference. If None, defaults to Gemini25FlashProvider.
            db: Optional TaskDatabase instance for persistent storage. If None, tasks are in-memory only.
            on_detection_event: Optional callback(task, new_note) fired when VLM emits a task update.
            on_model_usage: Optional callback(event_dict) fired when a model invocation completes.
        """
        self._tasks: Dict[str, Task] = {}  # task_id -> Task object
        self._io_manager = io_manager
        self._ingestors: Dict[str, VideoStreamIngestor] = {}  # io_id -> ingestor instance
        self._task_counter = 0  # Counter for task IDs, starting from 0
        self._db = db
        self._on_detection_event_cb = on_detection_event
        self._on_model_usage_cb = on_model_usage
        
        # Get model provider from environment variable if not provided
        if model_provider is None:
            model_provider = get_VLM_provider()
        self._model_provider = model_provider
        self._attach_usage_callback(self._model_provider)
        
        # Load persisted tasks from database
        if self._db is not None:
            self._load_tasks_from_db()
    
    def _load_tasks_from_db(self):
        """Load previously persisted tasks from the database on startup.
        
        When an IO manager is available, active camera tasks are resumed by
        recreating their ingestors. If a task cannot be resumed, it is marked
        as terminated. Without an IO manager, active tasks are terminated.
        """
        try:
            terminated_count = 0
            if self._io_manager is None:
                terminated_count = self._db.terminate_active_tasks()

            saved_tasks = self._db.load_all_tasks()
            resumable_tasks: List[Task] = []
            for t in saved_tasks:
                notes = [
                    NoteEntry(
                        content=n['content'],
                        timestamp=n['timestamp'],
                        note_id=n.get('note_id'),
                        frame_path=n.get('frame_path'),
                        video_path=n.get('video_path'),
                    )
                    for n in t['notes']
                ]
                task = Task(
                    task_id=t['task_id'],
                    task_number=t['task_number'],
                    task_desc=t['task_desc'],
                    task_note=notes,
                    done=t['done'],
                    io_id=t['io_id'],
                    status=t.get('status', STATUS_ACTIVE),
                    bot_id=t.get('bot_id'),
                    save_note_frames=t.get('save_note_frames'),
                    save_note_videos=t.get('save_note_videos'),
                )
                self._tasks[t['task_id']] = task
                if self._io_manager is not None and task.status == STATUS_ACTIVE and not task.done:
                    resumable_tasks.append(task)

            resumed_count = 0
            if resumable_tasks:
                resumed_count, extra_terminated = self._resume_tasks_from_db(resumable_tasks)
                terminated_count += extra_terminated
            
            # Resume counter from the highest existing task ID
            max_id = self._db.get_max_task_id()
            self._task_counter = max_id + 1
            
            if saved_tasks:
                logger.info(
                    f"Loaded {len(saved_tasks)} tasks from database "
                    f"(counter at {self._task_counter}, {resumed_count} resumed, {terminated_count} terminated)"
                )
        except Exception as e:
            logger.error(f"Failed to load tasks from database: {e}", exc_info=True)

    def _mark_task_terminated(self, task: Task) -> None:
        """Mark an active task as terminated when it cannot be resumed."""
        task.status = STATUS_TERMINATED
        if self._db is None:
            return
        try:
            self._db.update_task_status(task.task_id, STATUS_TERMINATED)
        except Exception as e:
            logger.error("Failed to mark task %s terminated: %s", task.task_id, e, exc_info=True)

    def _resume_tasks_from_db(self, tasks: List[Task]) -> tuple[int, int]:
        """Recreate ingestors for persisted active tasks when possible."""
        resumed_count = 0
        terminated_count = 0

        tasks_by_io: Dict[str, List[Task]] = {}
        for task in tasks:
            tasks_by_io.setdefault(task.io_id, []).append(task)

        for io_id, io_tasks in tasks_by_io.items():
            stream_info = self._io_manager.get_stream_info(io_id) if self._io_manager is not None else None
            if stream_info is None or stream_info.get("category") != "camera":
                logger.warning("Cannot resume tasks for io_id=%s because no camera stream is available", io_id)
                for task in io_tasks:
                    self._mark_task_terminated(task)
                    terminated_count += 1
                continue

            try:
                ingestor = self._create_ingestor_for_stream(io_id, stream_info)
            except Exception as e:
                logger.error("Failed to recreate ingestor for io_id=%s during startup: %s", io_id, e, exc_info=True)
                for task in io_tasks:
                    self._mark_task_terminated(task)
                    terminated_count += 1
                continue

            for task in io_tasks:
                try:
                    ingestor.add_task(task)
                    task.status = STATUS_ACTIVE
                    resumed_count += 1
                except Exception as e:
                    logger.error("Failed to resume task %s on io_id=%s: %s", task.task_id, io_id, e, exc_info=True)
                    self._mark_task_terminated(task)
                    terminated_count += 1

        return resumed_count, terminated_count

    def _resume_pending_tasks_for_io(self, io_id: str) -> int:
        """Best-effort resume of active or restart-terminated tasks for one device."""
        if self._io_manager is None:
            return 0
        if io_id in self._ingestors:
            return 0

        pending_tasks = [
            task for task in self._tasks.values()
            if task.io_id == io_id and not task.done and task.status in {STATUS_ACTIVE, STATUS_TERMINATED}
        ]
        if not pending_tasks:
            return 0

        stream_info = self._io_manager.get_stream_info(io_id)
        if stream_info is None or stream_info.get("category") != "camera":
            return 0

        try:
            ingestor = self._create_ingestor_for_stream(io_id, stream_info)
        except Exception as e:
            logger.error("Failed to recreate ingestor for io_id=%s while resuming pending tasks: %s", io_id, e, exc_info=True)
            return 0

        resumed_count = 0
        for task in pending_tasks:
            try:
                ingestor.add_task(task)
                task.status = STATUS_ACTIVE
                if self._db is not None:
                    self._db.update_task_status(task.task_id, STATUS_ACTIVE)
                resumed_count += 1
            except Exception as e:
                logger.error("Failed to resume task %s for io_id=%s: %s", task.task_id, io_id, e, exc_info=True)
        return resumed_count

    def _resume_pending_tasks(self, io_id: Optional[str] = None) -> int:
        """Best-effort resume for pending active/terminated tasks."""
        if io_id is not None:
            return self._resume_pending_tasks_for_io(io_id)

        resumed_count = 0
        io_ids = sorted({task.io_id for task in self._tasks.values() if not task.done and task.status in {STATUS_ACTIVE, STATUS_TERMINATED}})
        for pending_io_id in io_ids:
            resumed_count += self._resume_pending_tasks_for_io(pending_io_id)
        return resumed_count
    
    def _on_task_updated(self, task: Task, new_note: Optional[NoteEntry] = None):
        """Callback for video ingestors to persist task changes.
        
        Called when the ingestor appends a note or changes done status.
        """
        if self._db is None:
            if new_note is not None:
                new_note.clear_frame_bytes()
                new_note.clear_video_payload()
            return
        try:
            if new_note:
                should_persist_note_frames = self._should_persist_note_frames(task)
                should_persist_note_videos = self._should_persist_note_videos(task)
                frame_bytes = new_note.consume_frame_bytes() if should_persist_note_frames else None
                video_frames, video_fps = new_note.consume_video_payload() if should_persist_note_videos else (None, None)
                if not should_persist_note_frames:
                    new_note.clear_frame_bytes()
                if not should_persist_note_videos:
                    new_note.clear_video_payload()
                save_result = self._db.save_note(
                    task.task_id,
                    new_note.content,
                    new_note.timestamp,
                    frame_bytes=frame_bytes,
                    video_frames=video_frames,
                    video_fps=video_fps,
                )
                new_note.note_id = save_result.get('note_id')
                new_note.frame_path = save_result.get('frame_path')
                new_note.video_path = save_result.get('video_path')
            # When done is set, also update status to 'done'
            if task.done:
                task.status = STATUS_DONE
                self._db.update_task_done(task.task_id, task.done, status=STATUS_DONE)
            else:
                self._db.update_task_done(task.task_id, task.done)
        except Exception as e:
            logger.error(f"Failed to persist task update for {task.task_id}: {e}")

    def _should_persist_note_frames(self, task: Optional[Task] = None) -> bool:
        """Return whether task notes should persist their associated frames."""
        if task is not None and task.save_note_frames is not None:
            return bool(task.save_note_frames)
        raw_value = None
        if self._db is not None:
            try:
                raw_value = self._db.get_setting(_NOTE_FRAME_SETTING_KEY)
            except Exception as e:
                logger.error("Failed to load note-frame setting from database: %s", e, exc_info=True)
        if raw_value is None:
            raw_value = os.getenv(_NOTE_FRAME_SETTING_KEY)

        if raw_value is None:
            return True

        normalized = str(raw_value).strip().lower()
        if not normalized:
            return True
        if normalized in _TRUE_SETTING_VALUES:
            return True
        if normalized in _FALSE_SETTING_VALUES:
            return False
        logger.warning("Unrecognized %s value %r; defaulting to enabled", _NOTE_FRAME_SETTING_KEY, raw_value)
        return True

    def _should_persist_note_videos(self, task: Optional[Task] = None) -> bool:
        """Return whether task notes should persist evidence clips."""
        if task is not None and task.save_note_videos is not None:
            return bool(task.save_note_videos)
        raw_value = None
        if self._db is not None:
            try:
                raw_value = self._db.get_setting(_NOTE_VIDEO_SETTING_KEY)
            except Exception as e:
                logger.error("Failed to load note-video setting from database: %s", e, exc_info=True)
        if raw_value is None:
            raw_value = os.getenv(_NOTE_VIDEO_SETTING_KEY)

        if raw_value is None:
            return False

        normalized = str(raw_value).strip().lower()
        if not normalized:
            return False
        if normalized in _TRUE_SETTING_VALUES:
            return True
        if normalized in _FALSE_SETTING_VALUES:
            return False
        logger.warning("Unrecognized %s value %r; defaulting to disabled", _NOTE_VIDEO_SETTING_KEY, raw_value)
        return False

    def _attach_usage_callback(self, provider: Optional[BaseModelProvider]) -> None:
        """Attach the configured usage callback to a provider when supported."""
        if provider is None or self._on_model_usage_cb is None:
            return
        if hasattr(provider, "set_usage_callback"):
            try:
                provider.set_usage_callback(self._on_model_usage_cb)
            except Exception as e:
                logger.error("Failed to attach usage callback to %s: %s", type(provider).__name__, e, exc_info=True)

    def _apply_saved_ingestor_preferences(self, io_id: str, ingestor: VideoStreamIngestor) -> None:
        """Apply any persisted per-device ingestor settings to a live ingestor."""
        if self._db is None:
            return
        try:
            saved_threshold = self._db.get_ingestor_frame_diff_threshold(io_id)
            if saved_threshold is not None:
                ingestor.set_frame_diff_threshold(saved_threshold)
        except Exception as e:
            logger.error("Failed to apply saved ingestor preferences for %s: %s", io_id, e, exc_info=True)

    def _should_keep_network_camera_warm(self, io_id: str) -> bool:
        """Return whether this device should keep streaming even without active tasks."""
        if self._io_manager is None or not hasattr(self._io_manager, "is_network_camera"):
            return False
        try:
            if not self._io_manager.is_network_camera(io_id):
                return False
        except Exception as e:
            logger.error("Failed to determine whether %s is a network camera: %s", io_id, e, exc_info=True)
            return False

        raw_value = os.getenv("VIDEOMEMORY_KEEP_NETWORK_CAMERAS_WARM", "1")
        normalized = str(raw_value).strip().lower()
        return normalized not in _FALSE_SETTING_VALUES

    def _create_ingestor_for_stream(self, io_id: str, stream_info: Dict[str, Any]) -> VideoStreamIngestor:
        """Create and register a VideoStreamIngestor for a camera device."""
        if io_id in self._ingestors:
            return self._ingestors[io_id]

        stream_url = stream_info.get("url")
        if stream_url:
            camera_source = stream_info.get("pull_url") or stream_url
            logger.info(
                "Creating VideoStreamIngestor for network camera io_id=%s (pull url=%s)",
                io_id,
                camera_source,
            )
        else:
            try:
                camera_source = int(io_id)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid camera io_id '{io_id}'. Expected numeric index.") from exc

            expected_device_name = stream_info.get("name", "Unknown")

            try:
                current_cameras = self._io_manager._detector.detect_cameras()
                camera_found = False
                for idx, name in current_cameras:
                    if idx == camera_source:
                        if name != expected_device_name:
                            logger.warning(
                                "Camera index mismatch! io_id=%s expects '%s' but index %s is now '%s'. Camera order may have changed.",
                                io_id,
                                expected_device_name,
                                camera_source,
                                name,
                            )
                        camera_found = True
                        break
                if not camera_found:
                    logger.warning(
                        "Camera index %s not found in current device list. Device may have been disconnected.",
                        camera_source,
                    )
            except Exception as e:
                logger.debug(f"Could not verify camera index: {e}")

            logger.info(
                "Creating VideoStreamIngestor for io_id=%s (camera_index=%s, device=%s)",
                io_id,
                camera_source,
                expected_device_name,
            )

        ingestor = VideoStreamIngestor(
            camera_source,
            model_provider=self._model_provider,
            on_task_updated=self._on_task_updated,
            on_detection_event=self._emit_detection_event,
        )
        ingestor.set_keep_alive_without_tasks(self._should_keep_network_camera_warm(io_id))
        self._apply_saved_ingestor_preferences(io_id, ingestor)
        self._ingestors[io_id] = ingestor
        return ingestor

    def ensure_device_ingestor(self, io_id: str) -> Optional[VideoStreamIngestor]:
        """Create and start an ingestor for a camera device if needed."""
        if self._io_manager is None:
            return None

        stream_info = self._io_manager.get_stream_info(io_id)
        if stream_info is None:
            return None
        if stream_info.get("category") != "camera":
            return None

        ingestor = self._ingestors.get(io_id)
        if ingestor is None:
            ingestor = self._create_ingestor_for_stream(io_id, stream_info)

        ingestor.set_keep_alive_without_tasks(self._should_keep_network_camera_warm(io_id))
        ingestor.ensure_started()
        return ingestor

    def release_device_ingestor(self, io_id: str) -> bool:
        """Stop and forget an ingestor for a device, if one exists."""
        ingestor = self._ingestors.pop(io_id, None)
        if ingestor is None:
            return False

        try:
            ingestor.set_keep_alive_without_tasks(False)
        except Exception:
            pass

        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(ingestor.stop())
        except RuntimeError:
            ingestor_module = sys.modules.get(VideoStreamIngestor.__module__)
            bg_loop = getattr(ingestor_module, "_flask_background_loop", None)
            if bg_loop and bg_loop.is_running():
                asyncio.run_coroutine_threadsafe(ingestor.stop(), bg_loop)
            else:
                logger.warning("Could not stop ingestor for %s - no event loop", io_id)

        return True
    
    def add_task(
        self,
        io_id: str,
        task_description: str,
        bot_id: Optional[str] = None,
        save_note_frames: Optional[bool] = None,
        save_note_videos: Optional[bool] = None,
    ) -> Dict:
        """Add a new task for a specific IO stream.
        
        Args:
            io_id: The unique identifier of the IO stream
            task_description: Description of the task to be performed
            bot_id: Optional identifier of the bot that created this task (for multi-bot / debug)
            save_note_frames: Optional per-task override for saving note frames
            save_note_videos: Optional per-task override for saving note videos
        
        Returns:
            Dictionary containing the task information and status
        """
        # Check if io_manager is available and verify stream category
        if self._io_manager is None:
            return {
                "status": "error",
                "message": "IO manager not available. Cannot verify stream category.",
            }
        
        # Get stream info to check category
        stream_info = self._io_manager.get_stream_info(io_id)
        if stream_info is None:
            return {
                "status": "error",
                "message": f"Stream with io_id '{io_id}' not found",
            }
        
        # Check if it's a video stream (camera category)
        category = stream_info.get("category")
        if category != "camera":
            return {
                "status": "error",
                "message": f"Stream type '{category}' is not supported yet. Only video streams (camera) are currently supported.",
            }
        
        # Initialize video ingestor if not already created for this io_id
        if io_id not in self._ingestors:
            try:
                self._create_ingestor_for_stream(io_id, stream_info)
            except ValueError as exc:
                return {
                    "status": "error",
                    "message": str(exc),
                }
        
        # Create task with sequential ID starting from 0
        task_id = str(self._task_counter)
        self._task_counter += 1
        
        # Create Task object (will be shared by reference with video ingestor)
        task = Task(
            task_id=task_id,
            task_number=None,  # Will be set by video ingestor TODO: change task_number to task_id and have it be organized by task manager rather than the video ingestor
            task_desc=task_description,
            task_note=[],  # Empty list, will be shared by reference
            done=False,
            io_id=io_id,
            bot_id=bot_id,
            save_note_frames=save_note_frames,
            save_note_videos=save_note_videos,
        )
        
        
        self._tasks[task_id] = task
        
        # Persist to database
        if self._db:
            try:
                self._db.save_task(task)
            except Exception as e:
                logger.error(f"Failed to persist new task {task_id}: {e}")
        
        # Add task to the ingestor, passing the Task object (shared by reference)
        # This will automatically start the ingestor if not already running
        logger.debug(f"[DEBUG] TaskManager.add_task: About to call ingestor.add_task for io_id={io_id}")
        try:
            self._ingestors[io_id].add_task(task)
            logger.debug(f"[DEBUG] TaskManager.add_task: ingestor.add_task completed successfully")
        except Exception as e:
            logger.error(f"[ERROR] TaskManager.add_task: Exception in ingestor.add_task: {e}", exc_info=True)
            # Don't fail the task addition if ingestor start fails - task is still added
            # But log the error for debugging
        
        result = {
            "status": "success",
            "message": f"Task added successfully",
            "task_id": task_id,
            "io_id": io_id,
            "task_description": task_description,
        }
        if bot_id is not None:
            result["bot_id"] = bot_id
        result["save_note_frames"] = save_note_frames
        result["save_note_videos"] = save_note_videos
        return result

    def _emit_detection_event(self, task: Task, new_note: Optional[NoteEntry] = None):
        """Forward task detection updates to an optional integration callback."""
        if not self._on_detection_event_cb:
            return
        try:
            self._on_detection_event_cb(task, new_note)
        except Exception as e:
            logger.error(
                "Detection event callback failed for task %s: %s",
                getattr(task, "task_id", None),
                e,
                exc_info=True,
            )
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task information by task_id, including current notes and status.
        
        Args:
            task_id: The unique identifier of the task
        
        Returns:
            Dictionary with task info including notes (with serialized note history), or None if not found
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        
        # Return a copy with all information including task
        return task.to_dict()
    
    def list_tasks(self, io_id: Optional[str] = None) -> List[Dict]:
        """List all tasks, optionally filtered by io_id.
        
        Args:
            io_id: Optional filter to list only tasks for a specific IO stream
        
        Returns:
            List of task dictionaries
        """
        self._resume_pending_tasks(io_id)
        if io_id:
            return [task.to_dict() for task in self._tasks.values() if task.io_id == io_id]
        return [task.to_dict() for task in self._tasks.values()]

    def get_task_objects(self, io_id: Optional[str] = None) -> List[Task]:
        """Return live Task objects, optionally filtered by io_id."""
        self._resume_pending_tasks(io_id)
        if io_id:
            return [task for task in self._tasks.values() if task.io_id == io_id]
        return list(self._tasks.values())
    
    def update_task_status(self, task_id: str, done: bool) -> bool:
        """Update the status of a task.
        
        Args:
            task_id: The unique identifier of the task
            done: New done status
        
        Returns:
            True if updated successfully, False if task not found
        """
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.done = done
            task.status = STATUS_DONE if done else STATUS_ACTIVE
            
            # Persist to database
            if self._db:
                try:
                    self._db.update_task_done(task_id, done, status=task.status)
                except Exception as e:
                    logger.error(f"Failed to persist task status for {task_id}: {e}")
            
            return True
        return False
    
    def stop_task(self, task_id: str) -> Dict:
        """Stop a running task — marks it as done and removes it from the ingestor,
        but keeps it visible in the tasks list with all its notes preserved.
        
        Args:
            task_id: The unique identifier of the task
        
        Returns:
            Dictionary with status and message
        """
        if task_id not in self._tasks:
            return {"status": "error", "message": f"Task '{task_id}' not found"}
        
        task = self._tasks[task_id]
        
        if task.done:
            return {"status": "error", "message": f"Task '{task_id}' is already stopped"}
        
        io_id = task.io_id
        
        # Remove from ingestor (stops processing) but keep the Task object
        if io_id in self._ingestors:
            self._ingestors[io_id].set_keep_alive_without_tasks(self._should_keep_network_camera_warm(io_id))
            self._ingestors[io_id].remove_task(task.task_desc)
        
        # Mark as done
        task.done = True
        task.status = STATUS_DONE
        
        # Persist
        if self._db:
            try:
                self._db.update_task_done(task_id, True, status=STATUS_DONE)
            except Exception as e:
                logger.error(f"Failed to persist stop for task {task_id}: {e}")
        
        # Clean up ingestor if no active tasks remain for this io_id
        active_for_io = [t for t in self._tasks.values() if t.io_id == io_id and not t.done]
        if len(active_for_io) == 0 and io_id in self._ingestors:
            if self._should_keep_network_camera_warm(io_id):
                logger.info(
                    "VideoStreamIngestor for io_id=%s has no active tasks, but the network camera is configured to stay warm.",
                    io_id,
                )
            else:
                logger.info(f"VideoStreamIngestor for io_id={io_id} has no active tasks. Deleting ingestor.")
                del self._ingestors[io_id]
        
        return {
            "status": "success",
            "message": f"Task '{task_id}' stopped successfully",
            "task_id": task_id,
        }
    
    def remove_task(self, task_id: str) -> bool:
        """Permanently delete a task from the system.
        
        This removes the task entirely — from memory, the database, and the ingestor.
        Use stop_task instead if you want to keep the task visible with its history.
        
        Args:
            task_id: The unique identifier of the task
        
        Returns:
            True if removed successfully, False if task not found
        """
        if task_id not in self._tasks:
            return False
        task = self._tasks[task_id]
        # Get task info before removing
        io_id = task.io_id
        
        # Remove task from ingestor
        if io_id in self._ingestors:
            self._ingestors[io_id].set_keep_alive_without_tasks(self._should_keep_network_camera_warm(io_id))
            self._ingestors[io_id].remove_task(task.task_desc)
        
        # Remove task from manager
        del self._tasks[task_id]
        
        # Persist deletion to database
        if self._db:
            try:
                self._db.delete_task(task_id)
            except Exception as e:
                logger.error(f"Failed to delete task {task_id} from database: {e}")
        
        # Check if there are no more tasks for this io_id
        remaining_tasks = [task for task in self._tasks.values() if task.io_id == io_id]
        if len(remaining_tasks) == 0 and io_id in self._ingestors:
            if self._should_keep_network_camera_warm(io_id):
                logger.info(
                    "VideoStreamIngestor for io_id=%s has no tasks remaining, but the network camera is configured to stay warm.",
                    io_id,
                )
            else:
                # Delete the ingestor if no tasks remain
                logger.info(f"VideoStreamIngestor for io_id={io_id} has no tasks remaining. Deleting ingestor.")
                del self._ingestors[io_id]
        
        return True
    
    def get_latest_frame_for_device(self, io_id: str) -> Optional[Any]:
        """Get the latest frame from an active video ingestor for a device.
        
        Args:
            io_id: The IO device identifier
            
        Returns:
            Latest frame as numpy array, or None if no active ingestor or frame available
        """
        if io_id in self._ingestors:
            ingestor = self._ingestors[io_id]
            return ingestor.get_latest_frame()
        return None

    def reload_model_provider(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """Hot-reload the model provider and apply it to all active ingestors.

        This is used when model settings (API keys/provider model) change at runtime,
        so new inferences use the updated credentials/config without a process restart.

        Args:
            model_name: Optional model name override. If None/empty, uses
                VIDEO_INGESTOR_MODEL from the environment (or factory default).

        Returns:
            Dictionary summarizing the reload result.
        """
        requested_model = (model_name or "").strip() or None
        provider = get_VLM_provider(model_name=requested_model)
        self._attach_usage_callback(provider)
        self._model_provider = provider

        updated_ingestors = 0
        failed_ingestors: List[str] = []

        for io_id, ingestor in self._ingestors.items():
            try:
                # Prefer explicit ingestor API when available.
                if hasattr(ingestor, "set_model_provider"):
                    ingestor.set_model_provider(provider)
                else:
                    # Backward-compat fallback for older ingestor instances.
                    ingestor._model_provider = provider
                updated_ingestors += 1
            except Exception as exc:
                failed_ingestors.append(io_id)
                logger.error(
                    "Failed to update model provider for io_id=%s: %s",
                    io_id,
                    exc,
                    exc_info=True,
                )

        result = {
            "provider": type(provider).__name__,
            "updated_ingestors": updated_ingestors,
            "failed_ingestors": failed_ingestors,
        }
        logger.info(
            "Reloaded model provider to %s (model=%s, updated_ingestors=%d, failed=%d)",
            result["provider"],
            requested_model or "env/default",
            updated_ingestors,
            len(failed_ingestors),
        )
        return result
    
    def get_ingestor(self, io_id: str) -> Optional[VideoStreamIngestor]:
        """Get the active VideoStreamIngestor for a device, if any.
        
        Args:
            io_id: The IO device identifier
            
        Returns:
            The VideoStreamIngestor instance, or None if no ingestor is active for this device
        """
        self._resume_pending_tasks_for_io(io_id)
        return self._ingestors.get(io_id)
    
    def has_ingestor(self, io_id: str) -> bool:
        """Check whether there is an active ingestor for a device.
        
        Args:
            io_id: The IO device identifier
            
        Returns:
            True if an active ingestor exists for this device
        """
        self._resume_pending_tasks_for_io(io_id)
        return io_id in self._ingestors

    def get_ingestor_frame_skip_threshold(self, io_id: str) -> Dict[str, Any]:
        """Get the current or saved frame-skip threshold for a device."""
        ingestor = self._ingestors.get(io_id)
        if ingestor is not None:
            return self._build_frame_skip_threshold_response(
                io_id=io_id,
                threshold=ingestor.get_frame_diff_threshold(),
                source="active_ingestor",
                has_ingestor=True,
            )

        saved_threshold = None
        if self._db is not None:
            try:
                saved_threshold = self._db.get_ingestor_frame_diff_threshold(io_id)
            except Exception as e:
                logger.error("Failed to load saved frame diff threshold for %s: %s", io_id, e, exc_info=True)

        if saved_threshold is not None:
            return self._build_frame_skip_threshold_response(
                io_id=io_id,
                threshold=float(saved_threshold),
                source="database",
                has_ingestor=False,
            )

        return self._build_frame_skip_threshold_response(
            io_id=io_id,
            threshold=float(VideoStreamIngestor.DEFAULT_FRAME_DIFF_THRESHOLD),
            source="default",
            has_ingestor=False,
        )

    def set_ingestor_frame_skip_threshold(self, io_id: str, threshold: float) -> Dict[str, Any]:
        """Persist and, if possible, apply a frame-skip threshold for a device."""
        threshold_value = float(threshold)

        if self._db is not None:
            self._db.set_ingestor_frame_diff_threshold(io_id, threshold_value)

        ingestor = self._ingestors.get(io_id)
        if ingestor is not None:
            threshold_value = ingestor.set_frame_diff_threshold(threshold_value)
            source = "active_ingestor"
        else:
            threshold_value = max(0.0, min(255.0, threshold_value))
            source = "database"

        return self._build_frame_skip_threshold_response(
            io_id=io_id,
            threshold=float(threshold_value),
            source=source,
            has_ingestor=ingestor is not None,
        )

    def _build_frame_skip_threshold_response(
        self,
        *,
        io_id: str,
        threshold: float,
        source: str,
        has_ingestor: bool,
    ) -> Dict[str, Any]:
        """Build a consistent threshold payload for API/UI consumers."""
        threshold_value = float(threshold)
        return {
            "io_id": io_id,
            "average_pixel_diff_threshold": threshold_value,
            "frame_diff_threshold": threshold_value,
            "threshold_unit": _AVERAGE_PIXEL_DIFF_UNIT,
            "source": source,
            "has_ingestor": has_ingestor,
        }
    
    def edit_task(self, task_id: str, new_description: str) -> Dict:
        """Edit/update a task's description.
        
        Args:
            task_id: The unique identifier of the task
            new_description: The new description for the task
        
        Returns:
            Dictionary containing the updated task information and status
        """
        if task_id not in self._tasks:
            return {
                "status": "error",
                "message": f"Task '{task_id}' not found",
                "task_id": task_id,
            }
        
        # Get task info
        task = self._tasks[task_id]
        io_id = task.io_id

        
        # Update task description in Task object
        task.task_desc = new_description
        
        # Persist to database
        if self._db:
            try:
                self._db.update_task_desc(task_id, new_description)
            except Exception as e:
                logger.error(f"Failed to persist task edit for {task_id}: {e}")
        
        # Update task description in manager and Task object
        return {
            "status": "success",
            "message": f"Task updated successfully",
            "task_id": task_id,
            "io_id": io_id,
        }
