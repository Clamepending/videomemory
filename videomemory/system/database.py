"""SQLite database for persistent task and session metadata storage."""

import sqlite3
import logging
import os
import time
from pathlib import Path
from typing import List, Optional, Dict

logger = logging.getLogger('Database')


def get_default_data_dir() -> Path:
    """Get the default data directory (project_root/data/).
    
    database.py is at videomemory/system/database.py,
    so project root is 3 levels up.
    """
    return Path(__file__).parent.parent.parent / 'data'


class TaskDatabase:
    """Lightweight SQLite storage for tasks, notes, and session metadata.
    
    Uses WAL journal mode for good concurrent read performance,
    ideal for Raspberry Pi deployments.
    """
    
    def __init__(self, db_path: str = None):
        """Initialize the task database.
        
        Args:
            db_path: Path to the SQLite database file.
                     Defaults to <project_root>/data/videomemory.db
        """
        if db_path is None:
            db_path = str(get_default_data_dir() / 'videomemory.db')
        
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._init_db()
        logger.info(f"Task database initialized at {db_path}")
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get a new database connection with WAL mode and foreign keys."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """Create tables if they don't exist, and run migrations."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_number INTEGER,
                    task_desc TEXT NOT NULL,
                    done INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    io_id TEXT,
                    created_at REAL
                );

                CREATE TABLE IF NOT EXISTS task_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_notes_task_id
                    ON task_notes(task_id);

                CREATE TABLE IF NOT EXISTS session_metadata (
                    session_id TEXT PRIMARY KEY,
                    title TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            
            # Migration: add status column if missing (for existing DBs)
            columns = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
            if 'status' not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT 'active'")
                # Back-fill: done tasks get 'done', others stay 'active'
                conn.execute("UPDATE tasks SET status = 'done' WHERE done = 1")
                logger.info("Migrated tasks table: added status column")
    
    # ── Task methods ─────────────────────────────────────────────

    def save_task(self, task) -> None:
        """Insert or update a task."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id, task_number, task_desc, done, status, io_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (task.task_id, task.task_number, task.task_desc,
                 int(task.done), task.status, task.io_id, time.time())
            )
    
    def update_task_done(self, task_id: str, done: bool, status: str = None) -> None:
        """Update the done flag and optionally the status for a task."""
        with self._get_conn() as conn:
            if status is not None:
                conn.execute(
                    "UPDATE tasks SET done = ?, status = ? WHERE task_id = ?",
                    (int(done), status, task_id)
                )
            else:
                conn.execute(
                    "UPDATE tasks SET done = ? WHERE task_id = ?",
                    (int(done), task_id)
                )
    
    def update_task_status(self, task_id: str, status: str) -> None:
        """Update only the status for a task."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE task_id = ?",
                (status, task_id)
            )

    def terminate_active_tasks(self) -> int:
        """Mark all active (non-done) tasks as terminated. Returns count of affected rows."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'terminated' WHERE status = 'active' AND done = 0"
            )
            count = cursor.rowcount
            if count:
                logger.info(f"Marked {count} active task(s) as terminated (app restart)")
            return count

    def update_task_desc(self, task_id: str, desc: str) -> None:
        """Update only the description for a task."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE tasks SET task_desc = ? WHERE task_id = ?",
                (desc, task_id)
            )
    
    def delete_task(self, task_id: str) -> None:
        """Delete a task and its notes (CASCADE)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
    
    def save_note(self, task_id: str, content: str, timestamp: float) -> None:
        """Append a single note entry for a task."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO task_notes (task_id, content, timestamp) VALUES (?, ?, ?)",
                (task_id, content, timestamp)
            )
    
    def load_all_tasks(self) -> List[Dict]:
        """Load all tasks with their notes, ordered by task_id."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY CAST(task_id AS INTEGER)"
            ).fetchall()
            result = []
            for r in rows:
                notes = conn.execute(
                    "SELECT content, timestamp FROM task_notes WHERE task_id = ? ORDER BY timestamp",
                    (r['task_id'],)
                ).fetchall()
                result.append({
                    'task_id': r['task_id'],
                    'task_number': r['task_number'],
                    'task_desc': r['task_desc'],
                    'done': bool(r['done']),
                    'status': r['status'] if 'status' in r.keys() else ('done' if r['done'] else 'active'),
                    'io_id': r['io_id'],
                    'notes': [
                        {'content': n['content'], 'timestamp': n['timestamp']}
                        for n in notes
                    ]
                })
            return result
    
    def get_max_task_id(self) -> int:
        """Get the highest task_id (as int) to resume the counter. Returns -1 if empty."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(CAST(task_id AS INTEGER)) as m FROM tasks"
            ).fetchone()
            return row['m'] if row and row['m'] is not None else -1

    # ── Session metadata methods ─────────────────────────────────

    def save_session_metadata(self, session_id: str, title: str = '') -> None:
        """Create or update session metadata."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO session_metadata
                   (session_id, title, created_at)
                   VALUES (?, ?, coalesce(
                       (SELECT created_at FROM session_metadata WHERE session_id = ?),
                       ?
                   ))""",
                (session_id, title, session_id, time.time())
            )
    
    def update_session_title(self, session_id: str, title: str) -> None:
        """Update the display title for a session."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE session_metadata SET title = ? WHERE session_id = ?",
                (title, session_id)
            )
    
    def get_session_metadata(self, session_id: str) -> Optional[Dict]:
        """Get metadata for a single session."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT session_id, title, created_at FROM session_metadata WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row:
                return {
                    'session_id': row['session_id'],
                    'title': row['title'],
                    'created_at': row['created_at']
                }
            return None
    
    def list_session_metadata(self) -> List[Dict]:
        """List all session metadata, most recent first."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT session_id, title, created_at FROM session_metadata ORDER BY created_at DESC"
            ).fetchall()
            return [
                {
                    'session_id': r['session_id'],
                    'title': r['title'],
                    'created_at': r['created_at']
                }
                for r in rows
            ]
    
    def delete_session_metadata(self, session_id: str) -> None:
        """Delete session metadata."""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM session_metadata WHERE session_id = ?",
                (session_id,)
            )

    # ── Settings methods ─────────────────────────────────────────

    def get_setting(self, key: str) -> Optional[str]:
        """Get a single setting value. Returns None if not set."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row['value'] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a single setting value (upsert)."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO settings (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, value, time.time())
            )

    def delete_setting(self, key: str) -> None:
        """Delete a setting."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def get_all_settings(self) -> Dict[str, str]:
        """Get all settings as a dict."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r['key']: r['value'] for r in rows}

    def load_settings_to_env(self) -> int:
        """Load all saved settings into os.environ (overrides .env values).
        
        Returns:
            Number of settings loaded.
        """
        settings = self.get_all_settings()
        count = 0
        for key, value in settings.items():
            if value:  # Don't override with empty strings
                os.environ[key] = value
                count += 1
        if count:
            logger.info(f"Loaded {count} settings from database into environment")
        return count
