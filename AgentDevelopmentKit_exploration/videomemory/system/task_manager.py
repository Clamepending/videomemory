"""Task Manager for managing tasks associated with IO streams."""

import uuid
from typing import Dict, List, Optional
from system.stream_ingestors.video_stream_ingestor import VideoStreamIngestor


class TaskManager:
    """Manages tasks and their associations with IO streams."""
    
    def __init__(self, io_manager=None):
        """Initialize the task manager.
        
        Args:
            io_manager: Optional IO manager instance for checking stream categories
        """
        self._tasks: Dict[str, Dict] = {}  # task_id -> task info
        self._io_manager = io_manager
        self._ingestors: Dict[str, VideoStreamIngestor] = {}  # io_id -> ingestor instance
    
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
            self._ingestors[io_id] = VideoStreamIngestor(io_id)
        
        # Create task
        task_id = str(uuid.uuid4())[:8]  # Short UUID for readability
        
        # Create task_notes dictionary for the ingestor to update (flexible dict for any information)
        task_notes = {}
        
        task_info = {
            "task_id": task_id,
            "io_id": io_id,
            "description": task_description,
            "status": "pending",
            "task_notes": task_notes,
        }
        
        self._tasks[task_id] = task_info
        
        # Add task to the ingestor, passing the task_notes dictionary
        self._ingestors[io_id].add_task(task_description, task_notes)
        
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
            Dictionary with task info including notes, or None if not found
        """
        task_info = self._tasks.get(task_id)
        if task_info is None:
            return None
        
        # Return a copy with all information including task_notes
        return {
            "task_id": task_info.get("task_id"),
            "io_id": task_info.get("io_id"),
            "description": task_info.get("description"),
            "status": task_info.get("status"),
            "task_notes": task_info.get("task_notes", {}),
        }
    
    def list_tasks(self, io_id: Optional[str] = None) -> List[Dict]:
        """List all tasks, optionally filtered by io_id.
        
        Args:
            io_id: Optional filter to list only tasks for a specific IO stream
        
        Returns:
            List of task dictionaries
        """
        if io_id:
            return [task for task in self._tasks.values() if task["io_id"] == io_id]
        return list(self._tasks.values())
    
    def update_task_status(self, task_id: str, status: str) -> bool:
        """Update the status of a task.
        
        Args:
            task_id: The unique identifier of the task
            status: New status (e.g., "pending", "running", "completed", "failed")
        
        Returns:
            True if updated successfully, False if task not found
        """
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = status
            
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
        
        # Get task info before removing
        task_info = self._tasks[task_id]
        io_id = task_info["io_id"]
        task_description = task_info["description"]
        
        # Remove task from ingestor
        if io_id in self._ingestors:
            self._ingestors[io_id].remove_task(task_description)
        
        # Remove task from manager
        del self._tasks[task_id]
        
        # Check if there are no more tasks for this io_id
        remaining_tasks = [task for task in self._tasks.values() if task["io_id"] == io_id]
        if len(remaining_tasks) == 0 and io_id in self._ingestors:
            # Delete the ingestor if no tasks remain
            print(f"VideoStreamIngestor for io_id={io_id} has no tasks remaining. Deleting ingestor.")
            del self._ingestors[io_id]
        
        return True

