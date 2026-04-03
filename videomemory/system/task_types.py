"""Task-related data types."""

import time
from datetime import datetime
from typing import List, Optional


# Task lifecycle statuses
STATUS_ACTIVE = "active"          # Currently being processed by an ingestor
STATUS_DONE = "done"              # Completed successfully
STATUS_TERMINATED = "terminated"  # Was active but interrupted (e.g. app restart)


class NoteEntry:
    """Represents a single note entry with timestamp."""
    def __init__(
        self,
        content: str,
        timestamp: float = None,
        note_id: Optional[int] = None,
        frame_path: Optional[str] = None,
        frame_bytes: Optional[bytes] = None,
    ):
        self.content = content
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.note_id = note_id
        self.frame_path = frame_path
        self._frame_bytes = frame_bytes

    @property
    def frame_url(self) -> Optional[str]:
        """Return the API URL for this note's stored frame, if present."""
        if self.note_id is None or not self.frame_path:
            return None
        return f"/api/task-note/{self.note_id}/frame"

    def consume_frame_bytes(self) -> Optional[bytes]:
        """Return transient frame bytes and clear them from memory."""
        frame_bytes = self._frame_bytes
        self._frame_bytes = None
        return frame_bytes

    def clear_frame_bytes(self) -> None:
        """Drop any transient frame bytes attached to this note."""
        self._frame_bytes = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        # Convert timestamp to human-readable format
        timestamp_str = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "content": self.content,
            "timestamp": timestamp_str,
            "note_id": self.note_id,
            "has_frame": bool(self.frame_url),
            "frame_url": self.frame_url,
        }
        return payload
        

class Task:
    """Represents a task with its notes and status.
    
    Status lifecycle:
        active     -> done        (task completed by ingestor)
        active     -> terminated  (app restarted while task was running)
        terminated -> active      (task re-added after restart)
    """
    def __init__(self, task_number: int, task_desc: str, task_note: List[NoteEntry] = None,
                 done: bool = False, io_id: str = None, task_id: str = None,
                 status: str = STATUS_ACTIVE, bot_id: str = None):
        self.task_number = task_number
        self.task_id = task_id
        self.task_desc = task_desc
        self.task_note = task_note if task_note is not None else []  # List of NoteEntry objects (shared by reference)
        self.done = done
        self.io_id = io_id
        self.status = status
        self.bot_id = bot_id  # Optional; which bot created this task (debug / multi-bot compatibility)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = {
            "task_number": self.task_number,
            "task_id": self.task_id,
            "task_desc": self.task_desc,
            "task_note": [note.to_dict() if isinstance(note, NoteEntry) else note for note in self.task_note],
            "done": self.done,
            "io_id": self.io_id,
            "status": self.status,
        }
        if self.bot_id is not None:
            d["bot_id"] = self.bot_id
        return d
