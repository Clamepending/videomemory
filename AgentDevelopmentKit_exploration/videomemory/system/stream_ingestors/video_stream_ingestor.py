"""Video stream ingestor for managing video input streams."""

from typing import Dict


class VideoStreamIngestor:
    """Manages tasks for a video input stream."""
    
    def __init__(self, io_id: str):
        """Initialize the video stream ingestor.
        
        Args:
            io_id: The unique identifier of the IO stream
        """
        self.io_id = io_id
        self._task_notes: Dict[str, dict] = {}  # task_desc -> task_notes dict
        print(f"VideoStreamIngestor.__init__(io_id={io_id}) was called")
    
    def add_task(self, task_desc: str, task_notes: dict):
        """Add a task to the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be performed
            task_notes: Dictionary to store notes and status for this task (shared reference)
        """
        self._task_notes[task_desc] = task_notes
        print(f"VideoStreamIngestor.add_task(task_desc={task_desc}, task_notes={task_notes}) was called for io_id={self.io_id}")
        self._task_notes[task_desc]["number of claps"] = 0
    
    def remove_task(self, task_desc: str):
        """Remove a task from the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be removed
        """
        if task_desc in self._task_notes:
            del self._task_notes[task_desc]
        print(f"VideoStreamIngestor.remove_task(task_desc={task_desc}) was called for io_id={self.io_id}")

