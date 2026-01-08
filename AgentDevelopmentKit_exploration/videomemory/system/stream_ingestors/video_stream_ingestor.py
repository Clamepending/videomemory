"""Video stream ingestor for managing video input streams - Approach 4: Event-Driven with Message Queue."""

import asyncio
import logging
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Any, List
from asyncio import Queue as AsyncQueue
from collections import deque
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types as genai_types
import cv2
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Add videomemory directory to path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from system.task_types import NoteEntry, Task

# Load environment variables
load_dotenv()

# Set up logger for this module
logger = logging.getLogger('VideoStreamIngestor')

# Pydantic models for structured output
class TaskUpdate(BaseModel):
    """Model for task update output."""
    task_number: int = Field(..., description="The task number")
    task_note: str = Field(..., description="Updated description/note for the task")
    task_done: bool = Field(..., description="Whether the task is completed")


class SystemAction(BaseModel):
    """Model for system action output."""
    take_action: str = Field(..., description="Description of the action to take")


class VideoIngestorOutput(BaseModel):
    """Model for the complete output structure."""
    task_updates: List[TaskUpdate] = Field(default_factory=list, description="List of task updates")
    system_actions: List[SystemAction] = Field(default_factory=list, description="List of system actions to take")

class VideoStreamIngestor:
    """Manages tasks for a video input stream using event-driven architecture."""
    
    def __init__(self, camera_index: int, action_runner: Runner, session_service: Optional[BaseSessionService] = None, app_name: str = "videomemory_app"):
        """Initialize the video stream ingestor.
        
        Args:
            camera_index: The index of the camera to use
            action_runner: The runner for executing actions (see google adk: https://google.github.io/adk-docs/runtime/#key-components-of-the-runtime)
            session_service: The session service used by the runner (required to create sessions)
            app_name: The app name used by the runner (must match the runner's app_name)
        """
        self.camera_index = 0 # TODO: dont hard code to be the first camera. Modify the task manager to pass in the camera index.
        self._tasks_list: List[Task] = []  # List of Task objects (shared by reference with task_manager)
        self._frame_queue = AsyncQueue(maxsize=10)
        self._action_queue = AsyncQueue()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._camera: Optional[Any] = None  # Will hold cv2.VideoCapture when started
        self._latest_frame: Optional[Any] = None  # Store latest frame for debugging
        
        # History tracking: past 20 model outputs
        self._output_history: deque = deque(maxlen=20)  # Store last 20 model outputs
        
        # Rate limiting: track last request time (max 10 requests per minute = 6 seconds between requests)
        self._last_request_time: float = 0.0
        self._min_request_interval: float = 1.0  # 6 seconds = 10 requests per minute max
        
        # Initialize Google GenAI client
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found in environment. Multimodal LLM calls will fail.")
            self._genai_client = None
        else:
            try:
                self._genai_client = genai.Client(api_key=api_key)
                logger.info(f"Initialized Google GenAI client for camera index={self.camera_index}")
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI client: {e}")
                self._genai_client = None
        
        # Initialize action router runner for executing actions
        # Use provided action runner or create a new one
        self._action_runner = action_runner
        self._session_service = session_service
        self._action_user_id = f"video_ingestor_{self.camera_index}" # google adk each session requires a user ID but this is just a session foringesting a stream
        self._action_app_name = app_name  # Must match the runner's app_name
        self.session_id = f"video_ingestor_session_{self.camera_index}"
        
        logger.info(f"Initialized for camera index={self.camera_index}")
    
    async def start(self):
        """Start the video stream ingestor and all processing loops."""
        logger.debug(f"[DEBUG] VideoStreamIngestor.start: Called for camera_index={self.camera_index}")
        
        if self._running:
            logger.info(f"Already running for camera index={self.camera_index}")
            return
        
        # Create session for action runner if session_service is available
        if self._session_service:
            logger.debug(f"[DEBUG] VideoStreamIngestor.start: About to create session {self.session_id}")
            try:
                await self._session_service.create_session(
                    app_name=self._action_app_name,
                    user_id=self._action_user_id,
                    session_id=self.session_id
                )
                logger.info(f"Created session {self.session_id} for camera index={self.camera_index}")
            except Exception as e:
                # Check if it's a network error
                import httpx
                if isinstance(e, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
                    logger.error(f"[ERROR] VideoStreamIngestor.start: Network error creating session {self.session_id}: {type(e).__name__}: {e}", exc_info=True)
                else:
                    # Session might already exist, which is fine
                    logger.debug(f"Session creation for {self.session_id}: {e}")
        else:
            logger.warning(f"No session_service provided. Session {self.session_id} may not exist.")
        
        self._running = True
        logger.info(f"Starting ingestor for camera index={self.camera_index}")
        
        # Start all processing loops
        # Note: These tasks run concurrently in the background
        self._tasks = [
            asyncio.create_task(self._capture_loop(), name=f"capture_{self.camera_index}"),
            asyncio.create_task(self._process_loop(), name=f"process_{self.camera_index}"),
            asyncio.create_task(self._action_loop(), name=f"action_{self.camera_index}"),
        ]
        
        logger.info(f"Started {len(self._tasks)} processing loops for camera index={self.camera_index}")
        logger.info(f"Task status: {[t.get_name() for t in self._tasks]}")
        
        # Give tasks a moment to start and report any immediate errors
        await asyncio.sleep(0.1)
    
    async def _capture_loop(self):
        """Continuously capture frames from the video stream."""
        try:
            
            # On macOS, try AVFoundation backend first (better permission handling)
            import platform
            if platform.system() == 'Darwin':  # macOS
                self._camera = cv2.VideoCapture(self.camera_index, cv2.CAP_AVFOUNDATION)
            else:
                self._camera = cv2.VideoCapture(self.camera_index)
            
            # Check if camera opened successfully (for all platforms)
            if not self._camera.isOpened():
                error_msg = (
                    f"ERROR: Could not open camera {self.camera_index} for camera index={self.camera_index}\n"
                    f"  This is likely a macOS camera permission issue.\n"
                    f"  To fix:\n"
                    f"  1. Go to System Settings > Privacy & Security > Camera\n"
                    f"  2. Enable camera access for Terminal (or Python/your IDE)\n"
                    f"  3. Restart the application\n"
                    f"  Alternatively, the camera may be in use by another application."
                )
                logger.error(error_msg)
                # Update task notes to indicate camera failure
                for task in self._tasks_list:
                    error_note = NoteEntry(content="Camera access denied. Please grant camera permissions in System Settings.")
                    task.task_note.append(error_note)
                return
            
            logger.info(f"Started capture loop for camera index={self.camera_index}")
            
            while self._running:
                ret, frame = self._camera.read()
                if ret:
                    # Put frame in queue (non-blocking, will drop if queue full)
                    try:
                        self._frame_queue.put_nowait(frame)
                    except asyncio.QueueFull:
                        # Drop oldest frame if queue is full
                        try:
                            self._frame_queue.get_nowait()
                            self._frame_queue.put_nowait(frame)
                        except asyncio.QueueEmpty:
                            pass
                    
                await asyncio.sleep(0.1)  # 10fps
            
            self._camera.release()
            self._camera = None
            logger.info(f"Stopped capture loop for camera index={self.camera_index}")
        except asyncio.CancelledError:
            logger.info(f"Capture loop cancelled for camera index={self.camera_index}")
            if self._camera:
                self._camera.release()
                self._camera = None
        except Exception as e:
            logger.error(f"Error in capture loop for camera index={self.camera_index}: {e}", exc_info=True)
            self._running = False
    
    async def _process_loop(self):
        """Process frames through ML pipeline and update task notes."""
        try:
            logger.info(f"Started process loop for camera index={self.camera_index}")
            
            while self._running:
                try:
                    # Use timeout to allow checking _running flag periodically
                    frame = await asyncio.wait_for(
                        self._frame_queue.get(),
                        timeout=0.5
                    )
                    if frame is None:
                        continue
                    logger.debug(f"Process loop: Frame got from process loop queue for camera index={self.camera_index}")
                    
                    # Run ML processing with multimodal LLM
                    self._latest_frame = frame
                    results = await self._run_ml_inference(frame)
                    
                    # Store output in history
                    if results:
                        self._output_history.append(results)
                    
                    # Process results: update task notes and queue actions
                    if results:
                        await self._process_ml_results(results)
                            
                except asyncio.TimeoutError:
                    # Timeout allows us to check _running flag
                    continue
                except Exception as e:
                    logger.error(f"Error processing frame for camera index={self.camera_index}: {e}", exc_info=True)
                    continue
                    
        except asyncio.CancelledError:
            logger.info(f"Process loop cancelled for camera index={self.camera_index}")
        except Exception as e:
            logger.error(f"Error in process loop for camera index={self.camera_index}: {e}", exc_info=True)
            self._running = False
    
    async def _action_loop(self):
        """Execute actions based on task conditions."""
        try:
            logger.info(f"Started action loop for camera index={self.camera_index}")
            
            while self._running:
                try:
                    # Use timeout to allow checking _running flag periodically
                    action = await asyncio.wait_for(
                        self._action_queue.get(),
                        timeout=0.5
                    )
                    logger.debug(f"Action loop: Action {action} got from action loop queue for camera index={self.camera_index}")
                    if action is not None:
                        await self._execute_action(action)
                    
                except asyncio.TimeoutError:
                    # Timeout allows us to check _running flag
                    continue
                except Exception as e:
                    logger.error(f"Error executing action for camera index={self.camera_index}: {e}", exc_info=True)
                    continue
                    
        except asyncio.CancelledError:
            logger.info(f"Action loop cancelled for camera index={self.camera_index}")
        except Exception as e:
            logger.error(f"Error in action loop for camera index={self.camera_index}: {e}", exc_info=True)
    
    def _frame_to_base64(self, frame: Any) -> str:
        """Convert OpenCV frame to base64 encoded image."""
        try:
            _, buffer = cv2.imencode('.jpg', frame)
            return base64.b64encode(buffer).decode('utf-8')
        except Exception as e:
            logger.error(f"Error encoding frame: {e}")
            return ""
    
    def _build_prompt(self) -> str:
        """Build the prompt for the LLM based on tasks and history."""
        # Build tasks section
        tasks_lines = ["<tasks>"]
        for task in self._tasks_list:
            tasks_lines.append("<task>")
            tasks_lines.append(f"<task_number>{task.task_number}</task_number>")
            tasks_lines.append(f"<task_desc>{task.task_desc}</task_desc>")
            
            # Build note history section
            notes_list = task.task_note
            
            tasks_lines.append("<task_notes_history>")
            if notes_list:
                for note_entry in notes_list:
                    assert isinstance(note_entry, NoteEntry), "Note entry must be a NoteEntry object"
                    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(note_entry.timestamp))
                    tasks_lines.append(f"<note timestamp=\"{time_str}\">{note_entry.content}</note>")
            else:
                tasks_lines.append("<note timestamp=\"N/A\">No notes yet</note>")
            tasks_lines.append("</task_notes_history>")
            
            tasks_lines.append("</task>")
        tasks_lines.append("</tasks>")
        
        # Build history section (only model outputs)
        history_lines = ["<history>"]
        for output in self._output_history:
            history_lines.append("<output>")
            history_lines.append(f"<output_json>{json.dumps(output, default=str)}</output_json>")
            history_lines.append("</output>")
        history_lines.append("</history>")
        
        # Build instructions
        instructions = """<instructions>

You are the video ingestor. Your job is to output two lists of json objects.

The first list is to update task notes when you observe something relevant to a task in the current image. IMPORTANT: If you can provide a meaningful update to a task note based on what you see in the image, you MUST include it. This includes:
- New observations related to the task
- Changes in status or progress
- Updates to counts, positions, or states
- Any relevant information that advances tracking of the task

IMPORTANT: Task notes are maintained as a history. Each task_note you provide will be appended to the task's note history with a timestamp. You can see the full history of previous notes in the <task_notes_history> section for each task. Use this history to:
- Avoid repeating the same observations
- Build upon previous observations (e.g., "Previous clap count was 3, 1 more clap detected, now 4 claps detected")
- Track progression over time (e.g., "First subtask is complete, now working on second subtask")

Only update tasks to set the initial task note and when there's something new or relevant to report. If nothing has changed and there's nothing new to observe, you can return an empty task_updates list.

The second list is for system actions - only include actions if a task explicitly requires taking an action and the conditions are met in the video stream.

Write your output in this format and ONLY this format. Do not write anything but in exactly this format and nothing else.
[{task_number: <task number>, task_note: <new_description>, task_done: <True or False>}, ...], [{take_action: action_description}, ...]

examples:
When you observe a clap for "Count claps" task: [{task_number: 0, task_note: "Clap detected. Total count: 1 clap.", task_done: False}], []

When you observe 4 more claps (building on previous count): [{task_number: 0, task_note: "4 more claps detected. Total count: 5 claps.", task_done: False}], []

When you observe people for "Keep track of number of people": [{task_number: 1, task_note: "Currently 2 people visible in frame.", task_done: False}], []

When only 1 person is visible: [{task_number: 1, task_note: "1 person is visible in frame.", task_done: False}], []

When nothing relevant is observed: [], []

For multiple task updates: [{task_number: 0, task_note: "Clap count: 5", task_done: False}, {task_number: 1, task_note: "2 people visible", task_done: False}], []

When task is complete: [{task_number: 0, task_note: "Task completed - 10 claps counted", task_done: True}], [{take_action: "send notification that clap counting task is complete"}]
</instructions>"""
        
        return "\n".join(tasks_lines) + "\n\n" + "\n".join(history_lines) + "\n\n" + instructions
    
    async def _run_ml_inference(self, frame: Any) -> Optional[Dict[str, Any]]:
        """Run multimodal LLM inference on a frame."""
        if not self._genai_client or not self._tasks_list:
            return None
        
        # Rate limiting: ensure minimum interval between requests
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            await asyncio.sleep(self._min_request_interval - time_since_last)
        
        try:
            image_base64 = self._frame_to_base64(frame)
            if not image_base64:
                return None
            
            image_part = types.Part(
                inline_data=types.Blob(
                    data=base64.b64decode(image_base64),
                    mime_type="image/jpeg"
                )
            )
            text_part = types.Part(text=self._build_prompt())
            
            # Wrap synchronous API call in asyncio.to_thread to prevent blocking
            # This avoids connection pool issues when multiple frames are processed concurrently
            self._last_request_time = time.time()
            
            def _sync_generate_content():
                """Synchronous wrapper for generate_content to run in thread pool."""
                return self._genai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[image_part, text_part],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=VideoIngestorOutput.model_json_schema()
                    )
                )
            
            # Run the blocking call in a thread pool to avoid blocking the event loop
            response = await asyncio.to_thread(_sync_generate_content)
            
            output = VideoIngestorOutput(**json.loads(response.text))
            # logger.info(f"LLM inference prompt: {self._build_prompt()}")
            # logger.info(f"LLM inference output: {output}")
            return {
                "task_updates": [u.model_dump() for u in output.task_updates],
                "system_actions": [a.model_dump() for a in output.system_actions]
            }
        except Exception as e:
            # Handle network errors gracefully - these can happen due to connection issues
            # but shouldn't crash the entire processing loop
            import httpx
            if isinstance(e, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
                logger.warning(f"LLM inference network error (will skip this frame): {type(e).__name__}: {e}")
            else:
                logger.error(f"LLM inference error: {e}", exc_info=True)
            return None
    
    async def _process_ml_results(self, ml_results: Dict[str, Any]):
        """Process ML inference results: update task notes and queue actions."""
        if not ml_results:
            return
        
        # Update tasks - append new notes instead of overwriting
        for update in ml_results.get("task_updates", []):
            task = next((t for t in self._tasks_list if t.task_number == update.get("task_number")), None)
            if task:
                new_note_content = update.get("task_note", "")
                
                # Append new note entry with current timestamp
                if new_note_content:  # Only append if there's actual content
                    note_entry = NoteEntry(content=new_note_content)
                    task.task_note.append(note_entry)
                
                # Update done status
                if update.get("task_done"):
                    task.done = True
        
        # Queue actions
        for action in ml_results.get("system_actions", []):
            if action.get("take_action"):
                await self._action_queue.put(action["take_action"])
    
    async def _execute_action(self, action: str):
        """
        Execute an action using the shared admin agent runner.
        
        Args:
            action: String describing the action to execute
        """
        if not self._action_runner:
            logger.error("Action runner not available. Cannot execute action.")
            return
        
        try:
            content = genai_types.Content(role='user', parts=[genai_types.Part(text=f"Execute this action: {action}")])
            
            async for event in self._action_runner.run_async(
                user_id=self._action_user_id,
                session_id=self.session_id,
                new_message=content
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        logger.info(f"Action result: {event.content.parts[0].text}")
                    break
        except Exception as e:
            logger.error(f"Error executing action: {e}", exc_info=True)
    
    def add_task(self, task: Task):
        """Add a task to the video stream ingestor.
        
        Args:
            task: Task object (shared by reference with task_manager)
        """
        logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Called for task '{task.task_desc}', camera_index={self.camera_index}")
        
        # Set task number if not already set
        task.task_number = len(self._tasks_list)
        
        self._tasks_list.append(task)
        
        logger.info(f"Added task {task.task_number} '{task.task_desc}' for camera index={self.camera_index}")
        
        # Start the ingestor if not already running
        if not self._running:
            logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Ingestor not running, scheduling start()")
            # Schedule start in the event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Event loop is running, creating async task")
                    # Wrap start() to catch and log any errors
                    async def start_with_error_handling():
                        try:
                            logger.debug(f"[DEBUG] VideoStreamIngestor.start_with_error_handling: About to call start()")
                            await self.start()
                            logger.debug(f"[DEBUG] VideoStreamIngestor.start_with_error_handling: start() completed successfully")
                        except Exception as e:
                            logger.error(f"[ERROR] VideoStreamIngestor.start_with_error_handling: Error in start(): {e}", exc_info=True)
                            # Don't re-raise - log the error but don't crash
                    asyncio.create_task(start_with_error_handling())
                    logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Async task created")
                else:
                    logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Event loop not running, calling run_until_complete")
                    loop.run_until_complete(self.start())
            except RuntimeError as e:
                # No event loop running, will need to be started manually
                logger.warning(f"No event loop available. Call start() manually. Error: {e}")
            except Exception as e:
                logger.error(f"[ERROR] VideoStreamIngestor.add_task: Unexpected error scheduling start(): {e}", exc_info=True)
        else:
            logger.debug(f"[DEBUG] VideoStreamIngestor.add_task: Ingestor already running, skipping start()")
    
    def remove_task(self, task_desc: str):
        """Remove a task from the video stream ingestor.
        
        Args:
            task_desc: Description of the task to be removed
        """
        # Find and remove task from tasks list
        task_found = False
        for task in self._tasks_list:
            if task.task_desc == task_desc:
                self._tasks_list.remove(task)
                task_found = True
                break
        
        if task_found:
            # Renumber remaining tasks
            for i, task in enumerate(self._tasks_list):
                task.task_number = i
            logger.info(f"Removed task '{task_desc}' for camera index={self.camera_index}")
        else:
            logger.warning(f"Task '{task_desc}' not found for camera index={self.camera_index}")
        
        # Stop ingestor if no tasks remain (async call)
        if len(self._tasks_list) == 0:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.stop())
                else:
                    loop.run_until_complete(self.stop())
            except RuntimeError:
                logger.warning(f"Could not stop ingestor - no event loop")
    
    def edit_task(self, old_task_desc: str, new_task_desc: str):
        """Edit/update a task description in the video stream ingestor.
        
        This preserves the task notes list while updating the description.
        
        Args:
            old_task_desc: The current description of the task to be edited
            new_task_desc: The new description for the task
        """
        # Find task in tasks list
        task = None
        for t in self._tasks_list:
            if t.task_desc == old_task_desc:
                task = t
                break
        
        if task is None:
            logger.warning(f"Task '{old_task_desc}' not found for camera index={self.camera_index}, cannot edit")
            return False
        
        # Update task description (notes are already in the task object, so they're preserved)
        task.task_desc = new_task_desc
        
        logger.info(f"Edited task from '{old_task_desc}' to '{new_task_desc}' for camera index={self.camera_index}")
        return True
    
    async def stop(self):
        """Clean shutdown of all loops and tasks."""
        if not self._running:
            logger.info(f"Already stopped for camera index={self.camera_index}")
            return
        
        logger.info(f"Stopping ingestor for camera index={self.camera_index}")
        
        # 1. Signal shutdown
        self._running = False
        
        # 2. Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # 3. Wait for tasks to complete (with timeout)
        if self._tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Tasks didn't complete within timeout for camera index={self.camera_index}")
        
        # 4. Drain queues (prevents memory leaks)
        # Drain frame queue
        drained_frames = 0
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
                drained_frames += 1
            except asyncio.QueueEmpty:
                break
        
        if drained_frames > 0:
            logger.debug(f"Drained {drained_frames} frames from queue for camera index={self.camera_index}")
        
        # Drain action queue
        remaining_actions = []
        while not self._action_queue.empty():
            try:
                action = self._action_queue.get_nowait()
                remaining_actions.append(action)
            except asyncio.QueueEmpty:
                break
        
        if remaining_actions:
            logger.info(f"Discarding {len(remaining_actions)} queued actions for camera index={self.camera_index}")
        
        # 5. Clear task list
        self._tasks = []
        
        # 6. Release camera if still open
        if self._camera:
            self._camera.release()
            self._camera = None
        
        logger.info(f"Stopped ingestor for camera index={self.camera_index}")
    
    def get_latest_frame(self) -> Optional[Any]:
        """Get the latest frame (for debugging/visualization)."""
        return self._latest_frame
    
    def get_tasks_list(self) -> List[Task]:
        """Get the current tasks list as Task objects."""
        return self._tasks_list
    
    def get_prompt(self) -> str:
        """Get the current prompt that would be sent to the LLM."""
        return self._build_prompt()
    
    def get_output_history(self) -> List[Dict]:
        """Get the output history."""
        return list(self._output_history)
    
    def get_latest_output(self) -> Optional[Dict]:
        """Get the latest LLM output."""
        return self._output_history[-1] if self._output_history else None



# --- code the test the video ingestor standalone by calling just this script ---

def print_current_tasks(ingestor: VideoStreamIngestor):
    """Print the current state of all tasks."""
    tasks = ingestor.get_tasks_list()
    if tasks:
        print("=" * 60)
        print("CURRENT TASKS:")
        print("=" * 60)
        for task in tasks:
            status = "✓ DONE" if task.done else "⏳ ACTIVE"
            print(f"  [{task.task_number}] {status} - {task.task_desc}")
            
            # Print note history
            notes_history = task.task_note
            if notes_history:
                print(f"      Note History ({len(notes_history)} entries):")
                for note_entry in notes_history:
                    assert isinstance(note_entry, NoteEntry), "Note entry must be a NoteEntry object"
                    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(note_entry.timestamp))
                    content = note_entry.content
                    print(f"        [{time_str}] {content}")
        print("=" * 60)
    else:
        print("No tasks currently active.")

async def main():
    """Main function to run the video stream ingestor."""
    ingestor = VideoStreamIngestor(
        camera_index=0,
        action_runner=None,
        session_service=None,
        app_name="videomemory_app"
    )
    
    task = Task(
        task_number=-1,
        task_desc="keep track of the order of the number of fingers being held up",
        task_note=[],
        done=False
    )
    ingestor.add_task(task)
    print("Task added: keep track of the order of the number of fingers being held up")
    
    await ingestor.start()
    print("Video stream ingestor started.\n")
    
    try:
        last_output_count = 0
        cycle_count = 0
        while True:
            cycle_count += 1
            print("\n" + "-" * 60)
            print(f"CYCLE #{cycle_count}")
            print("-" * 60)
            
            # Print current tasks periodically
            print_current_tasks(ingestor)
            
            # Check for new outputs
            current_history = ingestor.get_output_history()
            if len(current_history) > last_output_count:
                output = current_history[-1]
                print(f"\n[New Response #{len(current_history)}]")
                
                for update in output.get("task_updates", []):
                    print(f"  Task {update.get('task_number')}: {update.get('task_note')}")
                
                for action in output.get("system_actions", []):
                    print(f"  Action: {action.get('take_action')}")
                
                last_output_count = len(current_history)
            
            await asyncio.sleep(2.0)  # Check every 2 seconds
            
    except KeyboardInterrupt:
        print("\nStopping video stream ingestor...")
        await ingestor.stop()
        print("Stopped.")


if __name__ == "__main__":
    asyncio.run(main())