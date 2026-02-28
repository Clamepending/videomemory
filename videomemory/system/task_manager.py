"""Task Manager for managing tasks associated with IO streams."""

import logging
from typing import Dict, List, Optional, Any, Callable
from .stream_ingestors.video_stream_ingestor import VideoStreamIngestor
from .io_manager import IOmanager
from .task_types import NoteEntry, Task, STATUS_ACTIVE, STATUS_DONE, STATUS_TERMINATED
from .database import TaskDatabase
from .model_providers import BaseModelProvider, get_VLM_provider
logger = logging.getLogger('TaskManager')

class TaskManager:
    """Manages tasks and their associations with IO streams."""
    
    def __init__(self, io_manager: IOmanager = None, model_provider: Optional[BaseModelProvider] = None, db: Optional[TaskDatabase] = None, on_detection_event: Optional[Callable[[Task, Optional[NoteEntry]], None]] = None):
        """Initialize the task manager.
        
        Args:
            io_manager: Optional IO manager instance for checking stream categories
            model_provider: Optional model provider for ML inference. If None, defaults to Gemini25FlashProvider.
            db: Optional TaskDatabase instance for persistent storage. If None, tasks are in-memory only.
            on_detection_event: Optional callback(task, new_note) fired when VLM emits a task update.
        """
        self._tasks: Dict[str, Task] = {}  # task_id -> Task object
        self._io_manager = io_manager
        self._ingestors: Dict[str, VideoStreamIngestor] = {}  # io_id -> ingestor instance
        self._task_counter = 0  # Counter for task IDs, starting from 0
        self._db = db
        self._on_detection_event_cb = on_detection_event
        
        # Get model provider from environment variable if not provided
        if model_provider is None:
            model_provider = get_VLM_provider()
        self._model_provider = model_provider
        
        # Load persisted tasks from database
        if self._db is not None:
            self._load_tasks_from_db()
    
    def _load_tasks_from_db(self):
        """Load previously persisted tasks from the database on startup.
        
        Any tasks that were still active (not done) are marked as 'terminated'
        since no ingestor is running for them after a restart.
        """
        try:
            # First, mark all active tasks in the DB as terminated
            terminated_count = self._db.terminate_active_tasks()
            
            # Now load all tasks (with updated statuses)
            saved_tasks = self._db.load_all_tasks()
            for t in saved_tasks:
                notes = [
                    NoteEntry(content=n['content'], timestamp=n['timestamp'])
                    for n in t['notes']
                ]
                task = Task(
                    task_id=t['task_id'],
                    task_number=t['task_number'],
                    task_desc=t['task_desc'],
                    task_note=notes,
                    done=t['done'],
                    io_id=t['io_id'],
                    status=t.get('status', STATUS_ACTIVE)
                )
                self._tasks[t['task_id']] = task
            
            # Resume counter from the highest existing task ID
            max_id = self._db.get_max_task_id()
            self._task_counter = max_id + 1
            
            if saved_tasks:
                logger.info(
                    f"Loaded {len(saved_tasks)} tasks from database "
                    f"(counter at {self._task_counter}, {terminated_count} terminated)"
                )
        except Exception as e:
            logger.error(f"Failed to load tasks from database: {e}", exc_info=True)
    
    def _on_task_updated(self, task: Task, new_note: Optional[NoteEntry] = None):
        """Callback for video ingestors to persist task changes.
        
        Called when the ingestor appends a note or changes done status.
        """
        if self._db is None:
            return
        try:
            if new_note:
                self._db.save_note(task.task_id, new_note.content, new_note.timestamp)
            # When done is set, also update status to 'done'
            if task.done:
                task.status = STATUS_DONE
                self._db.update_task_done(task.task_id, task.done, status=STATUS_DONE)
            else:
                self._db.update_task_done(task.task_id, task.done)
        except Exception as e:
            logger.error(f"Failed to persist task update for {task.task_id}: {e}")
    
    def add_task(self, io_id: str, task_description: str) -> Dict:
        """Add a new task for a specific IO stream.
        
        Args:
            io_id: The unique identifier of the IO stream
            task_description: Description of the task to be performed
        
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
            # Determine camera source: URL for network cameras, int index for local
            stream_url = stream_info.get("url")
            if stream_url:
                camera_source = stream_info.get("pull_url") or stream_url
                logger.info(f"Creating VideoStreamIngestor for network camera io_id={io_id} (pull url={camera_source})")
            else:
                try:
                    camera_source = int(io_id)
                except (ValueError, TypeError):
                    return {
                        "status": "error",
                        "message": f"Invalid camera io_id '{io_id}'. Expected numeric index.",
                    }
                
                expected_device_name = stream_info.get("name", "Unknown")
                
                try:
                    current_cameras = self._io_manager._detector.detect_cameras()
                    camera_found = False
                    for idx, name in current_cameras:
                        if idx == camera_source:
                            if name != expected_device_name:
                                logger.warning(
                                    f"Camera index mismatch! io_id={io_id} expects '{expected_device_name}' "
                                    f"but index {camera_source} is now '{name}'. Camera order may have changed."
                                )
                            camera_found = True
                            break
                    if not camera_found:
                        logger.warning(
                            f"Camera index {camera_source} not found in current device list. "
                            f"Device may have been disconnected."
                        )
                except Exception as e:
                    logger.debug(f"Could not verify camera index: {e}")
                
                logger.info(f"Creating VideoStreamIngestor for io_id={io_id} (camera_index={camera_source}, device={expected_device_name})")
            
            self._ingestors[io_id] = VideoStreamIngestor(
                camera_source, 
                model_provider=self._model_provider,
                on_task_updated=self._on_task_updated,
                on_detection_event=self._emit_detection_event,
            )
        
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
            io_id=io_id
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
        
        return {
            "status": "success",
            "message": f"Task added successfully",
            "task_id": task_id,
            "io_id": io_id,
            "task_description": task_description,
        }

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
        if io_id:
            return [task.to_dict() for task in self._tasks.values() if task.io_id == io_id]
        return [task.to_dict() for task in self._tasks.values()]
    
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
    
    def get_ingestor(self, io_id: str) -> Optional[VideoStreamIngestor]:
        """Get the active VideoStreamIngestor for a device, if any.
        
        Args:
            io_id: The IO device identifier
            
        Returns:
            The VideoStreamIngestor instance, or None if no ingestor is active for this device
        """
        return self._ingestors.get(io_id)
    
    def has_ingestor(self, io_id: str) -> bool:
        """Check whether there is an active ingestor for a device.
        
        Args:
            io_id: The IO device identifier
            
        Returns:
            True if an active ingestor exists for this device
        """
        return io_id in self._ingestors
    
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

    def reload_model_provider(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """Rebuild and hot-swap the active model provider.

        This applies new model/key settings immediately for new and running ingestors.
        """
        provider = get_VLM_provider(model_name=model_name)
        self._model_provider = provider

        updated_ingestors = 0
        for ingestor in self._ingestors.values():
            try:
                ingestor.set_model_provider(provider)
                updated_ingestors += 1
            except Exception as e:
                logger.error("Failed to hot-swap provider for ingestor: %s", e, exc_info=True)

        provider_name = type(provider).__name__
        logger.info(
            "Hot-reloaded model provider: %s (updated %d active ingestor(s))",
            provider_name,
            updated_ingestors,
        )
        return {
            "provider": provider_name,
            "updated_ingestors": updated_ingestors,
        }
