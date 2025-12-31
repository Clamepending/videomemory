"""Task Manager for managing tasks associated with IO streams."""

import uuid
from typing import Dict, List, Optional


class TaskManager:
    """Manages tasks and their associations with IO streams."""
    
    def __init__(self):
        """Initialize the task manager."""
        self._tasks: Dict[str, Dict] = {}  # task_id -> task info
    
    def add_task(self, io_id: str, task_description: str) -> Dict:
        """Add a new task for a specific IO stream.
        
        Args:
            io_id: The unique identifier of the IO stream
            task_description: Description of the task to be performed
        
        Returns:
            Dictionary containing the task information and status
        """
        task_id = str(uuid.uuid4())[:8]  # Short UUID for readability
        
        task_info = {
            "task_id": task_id,
            "io_id": io_id,
            "description": task_description,
            "status": "pending",
        }
        
        self._tasks[task_id] = task_info
        
        return {
            "status": "success",
            "message": f"Task added successfully",
            "task_id": task_id,
            "io_id": io_id,
            "task_description": task_description,
        }
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get task information by task_id.
        
        Args:
            task_id: The unique identifier of the task
        
        Returns:
            Dictionary with task info, or None if not found
        """
        return self._tasks.get(task_id)
    
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
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

