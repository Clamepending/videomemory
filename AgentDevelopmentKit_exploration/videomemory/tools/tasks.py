"""Task management tools."""

import json
import logging
from typing import Optional


class ToolContext:
    """Context object that holds system managers for tool functions."""
    
    def __init__(self, io_manager, task_manager):
        """Initialize the tool context with system managers.
        
        Args:
            io_manager: The IO manager instance
            task_manager: The task manager instance
        """
        self.io_manager = io_manager
        self.task_manager = task_manager


# Global context object (set by main.py)
_context: Optional[ToolContext] = None


def set_managers(io_manager, task_manager):
    """Set the IO manager and task manager instances via context.
    
    This should be called from main.py after creating the managers.
    
    Args:
        io_manager: The IO manager instance
        task_manager: The task manager instance
    """
    global _context
    _context = ToolContext(io_manager, task_manager)


def list_input_devices_with_ids() -> dict:
    """Lists all available input devices with their io_ids.
    
    Returns:
        dict: A dictionary containing lists of input devices organized by category,
              each device includes its io_id, category, and name.
    """
    print("--- list_input_devices_with_ids() was called ---")
    if _context is None:
        return {
            "status": "error",
            "message": "Tool context not initialized. System managers not available.",
        }
    
    if _context.io_manager is None:
        return {
            "status": "error",
            "message": "IO manager not available in context",
        }
    
    try:
        devices = _context.io_manager.list_all_streams()
        
        # Organize by category
        by_category = {}
        for device in devices:
            category = device["category"]
            if category not in by_category:
                by_category[category] = []
            by_category[category].append({
                "io_id": device["io_id"],
                "name": device["name"],
            })
        
        return {
            "status": "success",
            "input_devices": by_category,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list input devices: {str(e)}",
        }


def add_task(io_id: str, task_description: str) -> dict:
    """Adds a task for a specific input device using its io_id.
    
    Args:
        io_id: The unique identifier of the input device.
        task_description: A description of the task to be performed.
    
    Returns:
        dict: A dictionary containing the task information and status.
    """
    if _context is None:
        return {
            "status": "error",
            "message": "Tool context not initialized. System managers not available.",
        }
    
    if _context.task_manager is None:
        return {
            "status": "error",
            "message": "Task manager not available in context",
        }
    
    if _context.io_manager is None:
        return {
            "status": "error",
            "message": "IO manager not available in context",
        }
    
    try:
        # Verify the io_id exists
        device_info = _context.io_manager.get_stream_info(io_id)
        if device_info is None:
            return {
                "status": "error",
                "message": f"Input device with id '{io_id}' not found",
            }
        
        # Get device name for display, defaulting to "Unknown" if empty
        device_name = device_info.get('name', '').strip() or "Unknown"
        print(f"--- add_task({io_id} ({device_name}), {task_description}) was called ---")
        
        # Add the task
        logger = logging.getLogger('tasks')
        logger.debug(f"[DEBUG] add_task: About to call task_manager.add_task for io_id={io_id}, task={task_description}")
        try:
            result = _context.task_manager.add_task(io_id, task_description)
            logger.debug(f"[DEBUG] add_task: task_manager.add_task returned: {result}")
            result["device_info"] = device_info
            logger.info(f"[INFO] add_task: Successfully added task, returning result")
            return result
        except Exception as e:
            logger.error(f"[ERROR] add_task: Exception in task_manager.add_task: {e}", exc_info=True)
            raise
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to add task: {str(e)}",
        }


def list_tasks(io_id: Optional[str] = None) -> dict:
    """Lists all tasks, optionally filtered by io_id.
    
    Args:
        io_id: Optional filter to list only tasks for a specific input device.
    
    Returns:
        dict: A dictionary containing the list of tasks and status.
    """
    print(f"--- list_tasks(io_id={io_id}) was called ---")
    if _context is None:
        return {
            "status": "error",
            "message": "Tool context not initialized. System managers not available.",
        }
    
    if _context.task_manager is None:
        return {
            "status": "error",
            "message": "Task manager not available in context",
        }
    
    try:
        tasks = _context.task_manager.list_tasks(io_id)
        
        result = {
            "status": "success",
            "tasks": tasks,
            "count": len(tasks),
        }
        print(f"[DEBUG] list_tasks returning:\n{json.dumps(result, indent=2, default=str)}")
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list tasks: {str(e)}",
        }


def remove_task(task_id: str) -> dict:
    """Removes a task by its task_id.
    
    Args:
        task_id: The unique identifier of the task to remove.
    
    Returns:
        dict: A dictionary containing the removal status and message.
    """
    print(f"--- remove_task(task_id={task_id}) was called ---")
    if _context is None:
        return {
            "status": "error",
            "message": "Tool context not initialized. System managers not available.",
        }
    
    if _context.task_manager is None:
        return {
            "status": "error",
            "message": "Task manager not available in context",
        }
    
    try:
        success = _context.task_manager.remove_task(task_id)
        
        if success:
            return {
                "status": "success",
                "message": f"Task '{task_id}' removed successfully",
                "task_id": task_id,
            }
        else:
            return {
                "status": "error",
                "message": f"Task '{task_id}' not found",
                "task_id": task_id,
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to remove task: {str(e)}",
        }


def get_info_on(task_id: str) -> dict:
    """Gets detailed information about a task including current status and notes.
    
    Args:
        task_id: The unique identifier of the task to get information about.
    
    Returns:
        dict: A dictionary containing the task information including notes, status, and current info.
    """
    print(f"--- get_info_on(task_id={task_id}) was called ---")
    if _context is None:
        result = {
            "status": "error",
            "message": "Tool context not initialized. System managers not available.",
        }
        print(f"[DEBUG] get_info_on returning: {result}")
        return result
    
    if _context.task_manager is None:
        result = {
            "status": "error",
            "message": "Task manager not available in context",
        }
        print(f"[DEBUG] get_info_on returning: {result}")
        return result
    
    try:
        task_info = _context.task_manager.get_task(task_id)
        
        if task_info is None:
            result = {
                "status": "error",
                "message": f"Task '{task_id}' not found",
                "task_id": task_id,
            }
            print(f"[DEBUG] get_info_on returning: {result}")
            return result
        
        result = {
            "status": "success",
            "task": task_info,
        }
        print(f"[DEBUG] get_info_on returning success with task_info: {task_info}")
        return result
    except Exception as e:
        result = {
            "status": "error",
            "message": f"Failed to get task info: {str(e)}",
        }
        print(f"[DEBUG] get_info_on exception: {e}")
        return result


def edit_task(task_id: str, new_description: str) -> dict:
    """Edits/updates a task's description.
    
    This is useful when you want to amend an existing task, for example, to add an action
    to be triggered when a condition is met. The task will continue running with the same
    task_notes and status, but with the updated description.
    
    Args:
        task_id: The unique identifier of the task to edit.
        new_description: The new description for the task.
    
    Returns:
        dict: A dictionary containing the update status and updated task information.
    """
    print(f"--- edit_task(task_id={task_id}, new_description={new_description}) was called ---")
    if _context is None:
        return {
            "status": "error",
            "message": "Tool context not initialized. System managers not available.",
        }
    
    if _context.task_manager is None:
        return {
            "status": "error",
            "message": "Task manager not available in context",
        }
    
    try:
        result = _context.task_manager.edit_task(task_id, new_description)
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to edit task: {str(e)}",
        }

