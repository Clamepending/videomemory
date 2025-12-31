"""Task management tools."""

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
    print("--- add_task({io_id}, {task_description}) was called ---")
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
        
        # Add the task
        result = _context.task_manager.add_task(io_id, task_description)
        result["device_info"] = device_info
        
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to add task: {str(e)}",
        }

