"""Task Manager for managing tasks associated with IO streams."""

import logging
from typing import Dict, List, Optional, Any, Callable
from .stream_ingestors.video_stream_ingestor import VideoStreamIngestor
from .io_manager import IOmanager
from .task_types import NoteEntry, Task
from .database import TaskDatabase
from .model_providers import BaseModelProvider, get_VLM_provider
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
logger = logging.getLogger('TaskManager')

class TaskManager:
    """Manages tasks and their associations with IO streams."""
    
    def __init__(self, io_manager: IOmanager = None, action_runner: Runner = None, session_service: Optional[BaseSessionService] = None, app_name: str = "videomemory_app", model_provider: Optional[BaseModelProvider] = None, db: Optional[TaskDatabase] = None):
        """Initialize the task manager.
        
        Args:
            io_manager: Optional IO manager instance for checking stream categories
            action_runner: Optional Runner for executing actions, shared with video ingestors
            session_service: Optional session service used by the runner (required for video ingestor sessions)
            app_name: The app name used by the runner (must match the runner's app_name)
            model_provider: Optional model provider for ML inference. If None, defaults to Gemini25FlashProvider.
            db: Optional TaskDatabase instance for persistent storage. If None, tasks are in-memory only.
        """
        self._tasks: Dict[str, Task] = {}  # task_id -> Task object
        self._io_manager = io_manager
        self._ingestors: Dict[str, VideoStreamIngestor] = {}  # io_id -> ingestor instance
        self._action_runner = action_runner
        self._session_service = session_service
        self._app_name = app_name
        self._task_counter = 0  # Counter for task IDs, starting from 0
        self._db = db
        
        # Get model provider from environment variable if not provided
        if model_provider is None:
            model_provider = get_VLM_provider()
        self._model_provider = model_provider
        
        # Load persisted tasks from database
        if self._db is not None:
            self._load_tasks_from_db()
    
    def _load_tasks_from_db(self):
        """Load previously persisted tasks from the database on startup."""
        try:
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
                    io_id=t['io_id']
                )
                self._tasks[t['task_id']] = task
            
            # Resume counter from the highest existing task ID
            max_id = self._db.get_max_task_id()
            self._task_counter = max_id + 1
            
            if saved_tasks:
                logger.info(f"Loaded {len(saved_tasks)} tasks from database (counter at {self._task_counter})")
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
            # For cameras, io_id is now the OpenCV camera index as a string
            # Convert to int for VideoStreamIngestor
            try:
                camera_index = int(io_id)
            except (ValueError, TypeError):
                return {
                    "status": "error",
                    "message": f"Invalid camera io_id '{io_id}'. Expected numeric index.",
                }
            
            # Verify the camera index matches the expected device name
            # This helps catch cases where camera order has changed
            expected_device_name = stream_info.get("name", "Unknown")
            
            # Verify that the camera index actually corresponds to the expected device
            # by checking current device list
            try:
                current_cameras = self._io_manager._detector.detect_cameras()
                camera_found = False
                for idx, name in current_cameras:
                    if idx == camera_index:
                        if name != expected_device_name:
                            logger.warning(
                                f"Camera index mismatch! io_id={io_id} expects '{expected_device_name}' "
                                f"but index {camera_index} is now '{name}'. Camera order may have changed."
                            )
                        camera_found = True
                        break
                if not camera_found:
                    logger.warning(
                        f"Camera index {camera_index} not found in current device list. "
                        f"Device may have been disconnected."
                    )
            except Exception as e:
                logger.debug(f"Could not verify camera index: {e}")
            
            logger.info(f"Creating VideoStreamIngestor for io_id={io_id} (camera_index={camera_index}, device={expected_device_name})")
            
            self._ingestors[io_id] = VideoStreamIngestor(
                camera_index, 
                action_runner=self._action_runner,
                model_provider=self._model_provider,
                session_service=self._session_service,
                app_name=self._app_name,
                on_task_updated=self._on_task_updated
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
            
            # Persist to database
            if self._db:
                try:
                    self._db.update_task_done(task_id, done)
                except Exception as e:
                    logger.error(f"Failed to persist task status for {task_id}: {e}")
            
            return True
        return False
    
    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the manager.
        
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
