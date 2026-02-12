"""Task-related data types."""

import time
from datetime import datetime
from typing import List


# Task lifecycle statuses
STATUS_ACTIVE = "active"          # Currently being processed by an ingestor
STATUS_DONE = "done"              # Completed successfully
STATUS_TERMINATED = "terminated"  # Was active but interrupted (e.g. app restart)


class NoteEntry:
    """Represents a single note entry with timestamp."""
    def __init__(self, content: str, timestamp: float = None):
        self.content = content
        self.timestamp = timestamp if timestamp is not None else time.time()
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        # Convert timestamp to human-readable format
        timestamp_str = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "content": self.content,
            "timestamp": timestamp_str
        }
        

class Task:
    """Represents a task with its notes and status.
    
    Status lifecycle:
        active     -> done        (task completed by ingestor)
        active     -> terminated  (app restarted while task was running)
        terminated -> active      (task re-added after restart)
    """
    def __init__(self, task_number: int, task_desc: str, task_note: List[NoteEntry] = None,
                 done: bool = False, io_id: str = None, task_id: str = None,
                 status: str = STATUS_ACTIVE):
        self.task_number = task_number
        self.task_id = task_id
        self.task_desc = task_desc
        self.task_note = task_note if task_note is not None else []  # List of NoteEntry objects (shared by reference)
        self.done = done
        self.io_id = io_id
        self.status = status
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "task_number": self.task_number,
            "task_id": self.task_id,
            "task_desc": self.task_desc,
            "task_note": [note.to_dict() if isinstance(note, NoteEntry) else note for note in self.task_note],
            "done": self.done,
            "io_id": self.io_id,
            "status": self.status
        }

